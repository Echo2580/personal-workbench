"""Goal（长期任务）CRUD + 规划 / 习惯实例 / 进度 endpoints。

期 2：创建、列表、详情、PATCH、归档（DELETE=归档）；
期 3：``POST /goals/{id}/plan``（只返回 drafts，不落库）与
``POST /goals/{id}/tasks``（用户确认后批量落库，带 goalId/planRevision）；
期 4：``POST /goals/{id}/occurrences``（习惯实例，按自然日幂等）；
期 5：GET 详情附 ``progress`` 计算字段。

约定与 tasks/sources 一致：错误统一走 ``error_response``/``ApiError`` 信封；
Goal 自身校验失败用 ``goal_validation_failed``，规划/草稿校验失败用
``plan_validation_failed``。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.tasks.api import (
    ApiError,
    FieldError,
    api_error_response,
    current_time,
    error_response,
    note_commit_warning,
    request_data_root,
    storage_error_response,
)
from app.modules.tasks.api.dto import field_path as _field_path
from app.modules.tasks.domain import Goal, Source, Task
from app.modules.tasks.domain.goals import GoalKind, GoalStatus
from app.modules.tasks.services.model_adapter import (
    DeepSeekGoalPlanner,
    GoalPlanningModel,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.modules.tasks.services.planner import (
    PlanDraftError,
    build_manual_source,
    build_occurrence_days,
    build_occurrence_task_payloads,
    build_plan_task_payload,
    existing_task_dates,
    goal_progress,
    run_goal_plan,
    time_payload_date,
)
from app.modules.tasks.storage import SKIP_COMMIT, Snapshot, commit, load_snapshot


router = APIRouter()
logger = logging.getLogger("snap2todo.api")

MODEL_UNAVAILABLE_TEXT = "模型服务暂不可用，请稍后重试。"
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

LIST_STATUSES: frozenset[str] = frozenset({"all", "active", "done", "archived"})
LIST_KINDS: frozenset[str] = frozenset({"all", "plan", "habit"})

# 规划接口根键：POST /plan 只接受不可用日；POST /tasks 只接受 drafts/planRevision
_PLAN_ROOT_KEYS: frozenset[str] = frozenset({"unavailableDates"})
_SAVE_ROOT_KEYS: frozenset[str] = frozenset(
    {"drafts", "confirmedTasks", "planRevision"}
)

# POST 可写键（id/status/planRevision/createdAt/updatedAt 由服务端生成）
CREATE_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "title",
        "description",
        "startDate",
        "targetDate",
        "dailyCapacity",
        "constraints",
        "recurrence",
    }
)
# PATCH 可写键；kind 不允许修改（见 READ_ONLY_KEYS）
PATCH_KEYS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "startDate",
        "targetDate",
        "dailyCapacity",
        "constraints",
        "recurrence",
        "status",
    }
)
READ_ONLY_KEYS: frozenset[str] = frozenset(
    # status 在 PATCH 可写、创建时由服务端固定为 active，故仍视为只读键
    {"id", "kind", "status", "planRevision", "createdAt", "updatedAt"}
)
# PATCH 中允许显式 null 清空/回退的键
NULL_ALLOWED: frozenset[str] = frozenset(
    {"description", "targetDate", "dailyCapacity", "constraints", "recurrence"}
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RecurrenceInput(_StrictModel):
    """习惯重现规则输入；daily 时可省略 weekdays（服务端补 []）。"""

    freq: Literal["daily", "weekly"]
    weekdays: list[int] = Field(default_factory=list)
    time: str | None = None
    duration_minutes: int | None = Field(default=None, alias="durationMinutes")


class GoalCreateInput(_StrictModel):
    """POST /goals 请求体：kind/title/startDate 必填，其余按 kind 由模型校验。"""

    kind: GoalKind
    title: str
    description: str | None = None
    start_date: str = Field(alias="startDate")
    target_date: str | None = Field(default=None, alias="targetDate")
    daily_capacity: int | None = Field(default=None, alias="dailyCapacity")
    constraints: list[str] | None = None
    recurrence: RecurrenceInput | None = None


class GoalPatchInput(_StrictModel):
    """PATCH /goals/{id} 请求体：所有字段可选（省略=保持原值）。"""

    title: str | None = None
    description: str | None = None
    start_date: str | None = Field(default=None, alias="startDate")
    target_date: str | None = Field(default=None, alias="targetDate")
    daily_capacity: int | None = Field(default=None, alias="dailyCapacity")
    constraints: list[str] | None = None
    recurrence: RecurrenceInput | None = None
    status: GoalStatus | None = None


# ---- 期 3/4：规划与习惯实例输入 ------------------------------------------- #


class PlanTimeInput(_StrictModel):
    """规划草稿的时间输入：允许带 timeZone（规划输出原样回传），服务端固定上海。"""

    raw_expression: str | None = Field(alias="rawExpression")
    precision: Literal["datetime", "date", "day_part", "relative", "unknown"]
    resolved_value: str | None = Field(alias="resolvedValue")
    status: Literal["resolved", "needs_confirmation"]
    time_zone: str | None = Field(default=None, alias="timeZone")


class GoalPlanInput(_StrictModel):
    """POST /goals/{id}/plan 可选请求体：只有"不可用日"。"""

    unavailable_dates: list[str] = Field(default_factory=list, alias="unavailableDates")


class PlanDraftInput(_StrictModel):
    """POST /goals/{id}/tasks 的单个草稿（兼容 /plan 返回形状与确认链路字段）。"""

    draft_id: str | None = Field(default=None, alias="draftId")
    planned_date: str | None = Field(default=None, alias="plannedDate")
    title: str
    start_time: PlanTimeInput | None = Field(default=None, alias="startTime")
    due_time: PlanTimeInput | None = Field(default=None, alias="dueTime")
    requirements: list[str] = Field(default_factory=list)
    # 兼容确认链路草稿的附加字段：可回传，但不参与规划任务落库
    source_excerpt: str | None = Field(default=None, alias="sourceExcerpt")
    applicability: dict[str, Any] | None = None
    reminder: dict[str, Any] | None = None
    id: str | None = None


class SaveGoalTasksInput(_StrictModel):
    """POST /goals/{id}/tasks 请求体；drafts 与 confirmedTasks 二选一。"""

    drafts: list[PlanDraftInput] | None = None
    confirmed_tasks: list[PlanDraftInput] | None = Field(
        default=None, alias="confirmedTasks"
    )
    plan_revision: int | None = Field(default=None, alias="planRevision")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _validation_error_to_api_error(exc: ValidationError) -> ApiError:
    """Goal 输入的 pydantic 错误 → 既有错误信封。

    extra_forbidden（未知/只读键）→ 400 invalid_request；其余形状问题 →
    422 goal_validation_failed。plan/habit 互斥由 model_validator 报在模型根
    （loc 为空），这里把字段名落到 ``kind``，便于前端定位。
    """
    field_errors: list[FieldError] = []
    has_extra = False
    for err in exc.errors():
        location = _field_path(tuple(err.get("loc", ()))) or "kind"
        error_type = str(err.get("type", ""))
        if error_type == "extra_forbidden":
            has_extra = True
        field_errors.append(
            FieldError(
                field=location,
                code=error_type or "invalid",
                message=str(err.get("msg", "invalid")),
            )
        )
    if has_extra:
        return ApiError(400, "invalid_request", "包含不可写或未知字段。", field_errors)
    return ApiError(422, "goal_validation_failed", "长期任务字段校验失败。", field_errors)


def _reject_unwritable(payload: dict[str, Any], writable: frozenset[str]) -> ApiError | None:
    field_errors: list[FieldError] = []
    for key in payload:
        if key in writable:
            continue
        if key in READ_ONLY_KEYS:
            field_errors.append(
                FieldError(key, "read_only_field", "该字段为只读字段。")
            )
        else:
            field_errors.append(
                FieldError(key, "unknown_field", "该字段不可写或不存在。")
            )
    if field_errors:
        return ApiError(400, "invalid_request", "包含不可写或未知字段。", field_errors)
    return None


async def _read_json_object(
    request: Request, *, allow_empty: bool = False
) -> dict[str, Any] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - any parse failure is a 400
        return error_response(400, "invalid_request", "请求体必须是合法 JSON。")
    if not isinstance(payload, dict):
        return error_response(400, "invalid_request", "请求体必须是 JSON 对象。")
    if not payload and not allow_empty:
        return error_response(400, "invalid_request", "请求体不能为空对象。")
    return payload


def _recurrence_payload(dto: RecurrenceInput | None) -> dict[str, Any] | None:
    if dto is None:
        return None
    return {
        "freq": dto.freq,
        "weekdays": list(dto.weekdays),
        "time": dto.time,
        "durationMinutes": dto.duration_minutes,
    }


def _build_goal(
    payload: dict[str, Any],
) -> tuple[Goal | None, ApiError | None]:
    try:
        return Goal.model_validate(payload), None
    except ValidationError as exc:
        return None, _validation_error_to_api_error(exc)


def _build_patched_goal(
    current: Goal,
    body: GoalPatchInput,
    present: set[str],
    now: datetime,
) -> tuple[Goal | None, ApiError | None]:
    merged = current.model_dump(mode="json", by_alias=True)
    patch_values = body.model_dump(mode="json", by_alias=True)
    for key in present:
        merged[key] = patch_values[key]
    merged["updatedAt"] = now.isoformat()
    # planRevision 为只读：本期不随内容更新变化（预留给期 3 计划生成）。
    return _build_goal(merged)


def _goal_json(goal: Goal) -> dict[str, Any]:
    return goal.model_dump(mode="json", by_alias=True)


def _snapshot_with_goal(snapshot: Snapshot, goal: Goal) -> Snapshot:
    return Snapshot(
        schema_version=snapshot.schema_version,
        sources=snapshot.sources,
        tasks=snapshot.tasks,
        goals={**snapshot.goals, goal.id: goal},
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )


# --------------------------------------------------------------------------- #
# 期 3/4 helpers：模型注入、错误分型、输入校验
# --------------------------------------------------------------------------- #


def get_goal_planner(request: Request) -> GoalPlanningModel:
    """返回注入的规划适配器，默认 DeepSeekGoalPlanner（测试可注入 Mock）。"""
    planner = getattr(request.app.state, "goal_planner", None)
    if planner is None:
        planner = getattr(request.app.state, "goal_planning_model", None)
    if planner is None:
        planner = DeepSeekGoalPlanner()
        request.app.state.goal_planner = planner
    return planner


def _plan_model_failure(exc: Exception) -> JSONResponse:
    """模型失败分型：503/504/502；异常细节只进日志，不进响应。"""
    if isinstance(exc, ModelUnavailableError):
        logger.warning("规划模型不可用（已脱敏）：%s", type(exc).__name__)
        return error_response(503, "model_unavailable", MODEL_UNAVAILABLE_TEXT)
    if isinstance(exc, ModelTimeoutError):
        return error_response(504, "extraction_timeout", "模型调用超时，请重试。")
    if isinstance(exc, ModelOutputInvalidError):
        return error_response(502, "model_output_invalid", "模型输出无法解析。")

    field_errors: list[FieldError] = []
    if isinstance(exc, PlanDraftError):
        if exc.validation_error is not None:
            mapped = _validation_error_to_api_error(exc.validation_error)
            field_errors = [
                FieldError(
                    field=f"{exc.path}.{item.field}" if item.field else exc.path,
                    code=item.code,
                    message=item.message,
                )
                for item in mapped.field_errors
            ]
        else:
            field_errors = [FieldError(exc.path, "invalid", exc.message)]
    return error_response(
        502,
        "plan_validation_failed",
        "模型输出的规划字段不合法。",
        field_errors=field_errors,
    )


def _plan_input_error(exc: ValidationError, *, prefix: str = "") -> JSONResponse:
    """规划/草稿输入的 pydantic 错误 → 400（未知键）或 422 plan_validation_failed。"""
    field_errors: list[FieldError] = []
    has_extra = False
    for err in exc.errors():
        location = _field_path(tuple(err.get("loc", ())))
        if prefix:
            location = f"{prefix}.{location}" if location else prefix
        if not location:
            location = "drafts"
        error_type = str(err.get("type", ""))
        if error_type == "extra_forbidden":
            has_extra = True
        field_errors.append(
            FieldError(
                field=location,
                code=error_type or "invalid",
                message=str(err.get("msg", "invalid")),
            )
        )
    if has_extra:
        return error_response(
            400, "invalid_request", "包含不可写或未知字段。", field_errors=field_errors
        )
    return error_response(
        422,
        "plan_validation_failed",
        "规划草稿字段校验失败。",
        field_errors=field_errors,
    )


async def _read_optional_plan_body(request: Request) -> dict[str, Any] | JSONResponse:
    """读取可省略的 JSON 对象请求体（无 body / 空 body → {}）。"""
    try:
        raw = await request.body()
    except Exception:  # noqa: BLE001
        return error_response(400, "invalid_request", "请求体读取失败。")
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return error_response(400, "invalid_request", "请求体必须是合法 JSON。")
    if not isinstance(payload, dict):
        return error_response(400, "invalid_request", "请求体必须是 JSON 对象。")
    return payload


def _unknown_field_response(fields: list[str]) -> JSONResponse:
    return error_response(
        400,
        "invalid_request",
        "包含不可写或未知字段。",
        field_errors=[
            FieldError(field, "unknown_field", "该字段不可写或不存在。")
            for field in fields
        ],
    )


def _parse_date_value(value: str) -> date | None:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_unavailable_dates(values: list[str]) -> tuple[list[date], JSONResponse | None]:
    parsed: list[date] = []
    field_errors: list[FieldError] = []
    for index, raw in enumerate(values):
        day = _parse_date_value(raw)
        if day is None:
            field_errors.append(
                FieldError(
                    f"unavailableDates[{index}]",
                    "invalid_date",
                    "必须是真实 YYYY-MM-DD。",
                )
            )
        else:
            parsed.append(day)
    if field_errors:
        return [], error_response(
            422,
            "plan_validation_failed",
            "不可用日期格式不合法。",
            field_errors=field_errors,
        )
    # 去重但保持稳定顺序
    unique: list[date] = []
    seen: set[date] = set()
    for day in parsed:
        if day not in seen:
            seen.add(day)
            unique.append(day)
    return unique, None


def _time_payload(dto: PlanTimeInput | None) -> dict[str, Any] | None:
    if dto is None:
        return None
    return {
        "rawExpression": dto.raw_expression,
        "precision": dto.precision,
        "resolvedValue": dto.resolved_value,
        "timeZone": dto.time_zone or "Asia/Shanghai",
        "status": dto.status,
    }


def _build_goal_task_from_draft(
    draft: PlanDraftInput,
    index: int,
    *,
    goal: Goal,
    source_id: str,
    plan_revision: int,
    now: datetime,
) -> tuple[Task | None, JSONResponse | None]:
    """把单个确认草稿构造成待落库 Task；任何形状问题都返回 422。"""
    prefix = f"drafts[{index}]"
    title = draft.title.strip()
    if not title:
        return None, error_response(
            422,
            "plan_validation_failed",
            "规划草稿字段校验失败。",
            field_errors=[FieldError(f"{prefix}.title", "blank", "标题不能为空。")],
        )
    planned_date: date | None = None
    if draft.planned_date is not None:
        planned_date = _parse_date_value(draft.planned_date)
        if planned_date is None:
            return None, error_response(
                422,
                "plan_validation_failed",
                "规划草稿字段校验失败。",
                field_errors=[
                    FieldError(
                        f"{prefix}.plannedDate",
                        "invalid_date",
                        "必须是真实 YYYY-MM-DD。",
                    )
                ],
            )
    start_time = _time_payload(draft.start_time)
    due_time = _time_payload(draft.due_time)
    if planned_date is None:
        # 客户端没回传 plannedDate 时，从时间字段推导自然日（due 优先再 start）
        planned_date = time_payload_date(due_time) or time_payload_date(start_time)
    payload = build_plan_task_payload(
        draft_id=draft.draft_id or str(uuid.uuid4()),
        title=title,
        start_time=start_time,
        due_time=due_time,
        requirements=[item.strip() for item in draft.requirements if item.strip()],
        planned_date=planned_date,
        goal=goal,
        source_id=source_id,
        plan_revision=plan_revision,
        now=now,
    )
    try:
        return Task.model_validate(payload), None
    except ValidationError as exc:
        return None, _plan_input_error(exc, prefix=prefix)


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #


@router.post("/goals", status_code=201)
async def create_goal(request: Request) -> JSONResponse:
    payload = await _read_json_object(request, allow_empty=True)
    if isinstance(payload, JSONResponse):
        return payload

    failure = _reject_unwritable(payload, CREATE_KEYS)
    if failure is not None:
        return api_error_response(failure)

    try:
        body = GoalCreateInput.model_validate(payload)
    except ValidationError as exc:
        return api_error_response(_validation_error_to_api_error(exc))

    now = current_time()
    goal, failure = _build_goal(
        {
            "id": str(uuid.uuid4()),
            "kind": body.kind,
            "title": body.title,
            "description": body.description,
            "startDate": body.start_date,
            "targetDate": body.target_date,
            "dailyCapacity": body.daily_capacity,
            "constraints": body.constraints,
            "recurrence": _recurrence_payload(body.recurrence),
            "status": "active",
            "planRevision": 0,
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
        }
    )
    if failure is not None:
        return api_error_response(failure)
    assert goal is not None

    result = commit(
        request_data_root(request), lambda snapshot: snapshot.add_goal(goal)
    )
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("POST /goals", result)
    return JSONResponse(status_code=201, content={"goal": _goal_json(goal)})


@router.get("/goals")
async def list_goals(
    request: Request,
    status: str = "all",
    kind: str = "all",
) -> JSONResponse:
    if status not in LIST_STATUSES:
        return error_response(
            400,
            "invalid_status",
            "status 必须是 all、active、done 或 archived。",
            [FieldError("status", "invalid_enum", "只接受 all/active/done/archived。")],
        )
    if kind not in LIST_KINDS:
        return error_response(
            400,
            "invalid_kind",
            "kind 必须是 all、plan 或 habit。",
            [FieldError("kind", "invalid_enum", "只接受 all/plan/habit。")],
        )

    loaded = load_snapshot(request_data_root(request))
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None

    goals = list(loaded.snapshot.goals.values())
    if status != "all":
        goals = [goal for goal in goals if goal.status == status]
    if kind != "all":
        goals = [goal for goal in goals if goal.kind == kind]

    # createdAt 倒序；同一时刻按 id 升序（两次稳定排序，与 /tasks 一致）
    goals.sort(key=lambda goal: goal.id)
    goals.sort(key=lambda goal: goal.created_at, reverse=True)

    return JSONResponse(
        status_code=200,
        content={"goals": [_goal_json(goal) for goal in goals]},
    )


@router.get("/goals/{goal_id}")
async def get_goal(goal_id: str, request: Request) -> JSONResponse:
    loaded = load_snapshot(request_data_root(request))
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None

    goal = loaded.snapshot.goals.get(goal_id)
    if goal is None:
        return error_response(404, "goal_not_found", "长期任务不存在。")

    # 期 5：进度为计算字段（不落库），按该 goalId 的任务统计
    progress = goal_progress(
        goal_id, list(loaded.snapshot.tasks.values()), current_time().date()
    )
    return JSONResponse(
        status_code=200,
        content={"goal": _goal_json(goal), "progress": progress},
    )


@router.patch("/goals/{goal_id}")
async def patch_goal(goal_id: str, request: Request) -> JSONResponse:
    payload = await _read_json_object(request)
    if isinstance(payload, JSONResponse):
        return payload

    failure = _reject_unwritable(payload, PATCH_KEYS)
    if failure is not None:
        return api_error_response(failure)

    try:
        body = GoalPatchInput.model_validate(payload)
    except ValidationError as exc:
        return api_error_response(_validation_error_to_api_error(exc))

    present = set(payload)
    for key in present:
        if key not in NULL_ALLOWED and payload[key] is None:
            return error_response(
                422,
                "goal_validation_failed",
                f"{key} 不允许为 null。",
                [
                    FieldError(
                        key, "null_not_allowed", "该字段不允许为 null。"
                    )
                ],
            )

    root = request_data_root(request)
    now = current_time()

    loaded = load_snapshot(root)
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None
    current = loaded.snapshot.goals.get(goal_id)
    if current is None:
        return error_response(404, "goal_not_found", "长期任务不存在。")

    # 先在锁外构建一次，非法请求不触发任何写入
    probe, failure = _build_patched_goal(current, body, present, now)
    if failure is not None:
        return api_error_response(failure)
    assert probe is not None

    outcome: dict[str, Any] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        latest = snapshot.goals.get(goal_id)
        if latest is None:
            outcome["error"] = ApiError(404, "goal_not_found", "长期任务不存在。")
            return SKIP_COMMIT  # type: ignore[return-value]
        replacement, failure = _build_patched_goal(latest, body, present, now)
        if failure is not None:
            outcome["error"] = failure
            return SKIP_COMMIT  # type: ignore[return-value]
        assert replacement is not None
        return _snapshot_with_goal(snapshot, replacement)

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    if "error" in outcome:
        return api_error_response(outcome["error"])
    note_commit_warning("PATCH /goals", result)

    assert result.snapshot is not None
    goal = result.snapshot.goals.get(goal_id)
    assert goal is not None
    return JSONResponse(status_code=200, content={"goal": _goal_json(goal)})


@router.delete("/goals/{goal_id}")
async def archive_goal(goal_id: str, request: Request) -> JSONResponse:
    """DELETE = 归档：status=archived，不物理删除，也不影响任务。"""
    root = request_data_root(request)
    now = current_time()
    outcome: dict[str, Any] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        current = snapshot.goals.get(goal_id)
        if current is None:
            outcome["error"] = ApiError(404, "goal_not_found", "长期任务不存在。")
            return SKIP_COMMIT  # type: ignore[return-value]
        if current.status == "archived":
            # 重复归档幂等：不产生新的写盘
            outcome["goal"] = current
            return SKIP_COMMIT  # type: ignore[return-value]
        archived_payload = current.model_dump(mode="json", by_alias=True)
        archived_payload["status"] = "archived"
        archived_payload["updatedAt"] = now.isoformat()
        try:
            archived = Goal.model_validate(archived_payload)
        except ValidationError as exc:  # pragma: no cover - 落盘数据已通过校验
            outcome["error"] = _validation_error_to_api_error(exc)
            return SKIP_COMMIT  # type: ignore[return-value]
        outcome["goal"] = archived
        return _snapshot_with_goal(snapshot, archived)

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("DELETE /goals", result)
    if "error" in outcome:
        return api_error_response(outcome["error"])
    goal = outcome["goal"]
    return JSONResponse(status_code=200, content={"goal": _goal_json(goal)})


# --------------------------------------------------------------------------- #
# 期 3：AI 规划（只返回 drafts，不落库）与确认保存
# --------------------------------------------------------------------------- #


def _goal_active_failure(goal: Goal) -> JSONResponse | None:
    """期 3.4：归档（archived）/已完成（done）目标不允许继续规划或生成实例。"""
    if goal.status != "active":
        return error_response(
            409,
            "goal_not_active",
            "长期任务已归档或已完成，无法继续操作。",
        )
    return None


@router.post("/goals/{goal_id}/plan")
async def create_goal_plan(goal_id: str, request: Request) -> JSONResponse:
    """补空缺规划：只调模型并返回 drafts；drafts 由 /tasks 确认后才落库。"""
    payload = await _read_optional_plan_body(request)
    if isinstance(payload, JSONResponse):
        return payload
    unknown = [key for key in payload if key not in _PLAN_ROOT_KEYS]
    if unknown:
        return _unknown_field_response(unknown)
    try:
        body = GoalPlanInput.model_validate(payload)
    except ValidationError as exc:
        return _plan_input_error(exc)
    unavailable, failure = _parse_unavailable_dates(body.unavailable_dates)
    if failure is not None:
        return failure

    root = request_data_root(request)
    loaded = load_snapshot(root)
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None
    goal = loaded.snapshot.goals.get(goal_id)
    if goal is None:
        return error_response(404, "goal_not_found", "长期任务不存在。")
    # 期 3.4：归档/已完成目标直接 409（不调模型、不写库、revision 不变）
    failure = _goal_active_failure(goal)
    if failure is not None:
        return failure
    if goal.kind != "plan":
        return error_response(
            422,
            "goal_not_plan",
            "只有 plan 型长期任务可以生成计划。",
        )

    now = current_time()
    try:
        planned = run_goal_plan(
            goal,
            list(loaded.snapshot.tasks.values()),
            get_goal_planner(request),
            now.date(),
            unavailable,
        )
    except (
        ModelUnavailableError,
        ModelTimeoutError,
        ModelOutputInvalidError,
        PlanDraftError,
    ) as exc:
        return _plan_model_failure(exc)

    if not planned.model_called:
        # 无缺口：不调模型、不消耗规划轮次、不写库
        return JSONResponse(
            status_code=200,
            content={
                "planRevision": goal.plan_revision,
                "suggestedTargetDate": None,
                "drafts": [],
                "rawCount": 0,
                "dropped": 0,
            },
        )

    # 期 3.3：模型返回了任务但全部被过滤（缺日期/越界/超容量）→ 502，
    # 不能返回成功空结果伪装成"没有空缺"；全丢按失败处理：不写库、不递增。
    if planned.raw_count > 0 and not planned.drafts:
        return error_response(
            502,
            "plan_validation_failed",
            "模型返回的计划缺少可用日期。",
            field_errors=[
                FieldError(
                    "drafts",
                    "missing_usable_date",
                    "模型返回的任务均缺少可用日期。",
                )
            ],
        )

    # 期 3.3：模型确认没有返回任务（rawCount=0）→ 成功空结果，
    # 但只有"成功且确有草稿"才计规划轮次，这里不写盘、不递增。
    if not planned.drafts:
        return JSONResponse(
            status_code=200,
            content={
                "planRevision": goal.plan_revision,
                "suggestedTargetDate": planned.suggested_target_date,
                "drafts": [],
                "rawCount": planned.raw_count,
                "dropped": planned.dropped,
            },
        )

    # 真正完成一次有效规划（有草稿）：planRevision +1
    # （仅此一次写库，drafts 本身仍不落库）
    outcome: dict[str, Any] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        latest = snapshot.goals.get(goal_id)
        if latest is None:
            outcome["error"] = ApiError(404, "goal_not_found", "长期任务不存在。")
            return SKIP_COMMIT  # type: ignore[return-value]
        updated_payload = latest.model_dump(mode="json", by_alias=True)
        updated_payload["planRevision"] = latest.plan_revision + 1
        updated_payload["updatedAt"] = now.isoformat()
        try:
            updated = Goal.model_validate(updated_payload)
        except ValidationError as exc:
            outcome["error"] = _validation_error_to_api_error(exc)
            return SKIP_COMMIT  # type: ignore[return-value]
        outcome["revision"] = updated.plan_revision
        return _snapshot_with_goal(snapshot, updated)

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("POST /goals/plan", result)
    if "error" in outcome:
        return api_error_response(outcome["error"])

    return JSONResponse(
        status_code=200,
        content={
            "planRevision": outcome["revision"],
            "suggestedTargetDate": planned.suggested_target_date,
            "drafts": planned.drafts,
            "rawCount": planned.raw_count,
            "dropped": planned.dropped,
        },
    )


@router.post("/goals/{goal_id}/tasks")
async def save_goal_tasks(goal_id: str, request: Request) -> JSONResponse:
    """用户确认后批量落库规划 drafts：写入 tasks 带 goalId + planRevision。"""
    payload = await _read_json_object(request)
    if isinstance(payload, JSONResponse):
        return payload
    unknown = [key for key in payload if key not in _SAVE_ROOT_KEYS]
    if unknown:
        return _unknown_field_response(unknown)
    if "drafts" in payload and "confirmedTasks" in payload:
        return error_response(
            400,
            "invalid_request",
            "drafts 与 confirmedTasks 只能提供其一。",
        )
    try:
        body = SaveGoalTasksInput.model_validate(payload)
    except ValidationError as exc:
        return _plan_input_error(exc)

    drafts = body.drafts if body.drafts is not None else body.confirmed_tasks
    if drafts is None:
        return error_response(
            422,
            "plan_validation_failed",
            "必须提供 drafts 数组。",
            field_errors=[FieldError("drafts", "missing", "缺少 drafts 数组。")],
        )
    if not drafts:
        return error_response(
            422,
            "empty_drafts",
            "规划草稿列表为空。",
        )

    root = request_data_root(request)
    now = current_time()
    loaded = load_snapshot(root)
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None
    goal = loaded.snapshot.goals.get(goal_id)
    if goal is None:
        return error_response(404, "goal_not_found", "长期任务不存在。")

    # 期 3.4：planRevision 服务端权威——忽略客户端传值，一律使用当前 goal 值，
    # 避免客户端用旧/任意 revision 给任务打标。
    plan_revision = goal.plan_revision

    source_payload = build_manual_source(f"长期任务规划：{goal.title}", now)
    source = Source.model_validate(source_payload)

    prepared: list[Task] = []
    for index, draft in enumerate(drafts):
        task, failure = _build_goal_task_from_draft(
            draft,
            index,
            goal=goal,
            source_id=source.id,
            plan_revision=plan_revision,
            now=now,
        )
        if failure is not None:
            return failure
        assert task is not None
        prepared.append(task)

    outcome: dict[str, Any] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        latest = snapshot.goals.get(goal_id)
        if latest is None:
            outcome["error"] = ApiError(404, "goal_not_found", "长期任务不存在。")
            return SKIP_COMMIT  # type: ignore[return-value]
        existing_by_draft = {
            task.draft_id: task
            for task in snapshot.tasks.values()
            if task.goal_id == goal_id
        }
        ordered: list[Task] = []
        created: list[Task] = []
        for task in prepared:
            found = existing_by_draft.get(task.draft_id)
            if found is not None:
                ordered.append(found)
                continue
            ordered.append(task)
            created.append(task)
            existing_by_draft[task.draft_id] = task
        if not created:
            # 重复提交同一批 drafts：幂等返回既有任务，不写盘
            outcome["tasks"] = ordered
            return SKIP_COMMIT  # type: ignore[return-value]
        updated = snapshot.add_source(source)
        for task in created:
            updated = updated.add_task(task)
        outcome["tasks"] = ordered
        return updated

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("POST /goals/tasks", result)
    if "error" in outcome:
        return api_error_response(outcome["error"])

    tasks = outcome["tasks"]
    return JSONResponse(
        status_code=200,
        content={
            "tasks": [
                task.model_dump(mode="json", by_alias=True) for task in tasks
            ]
        },
    )


# --------------------------------------------------------------------------- #
# 期 4：习惯实例（未来 14 天，按自然日幂等）
# --------------------------------------------------------------------------- #


@router.post("/goals/{goal_id}/occurrences")
async def create_goal_occurrences(goal_id: str, request: Request) -> JSONResponse:
    """习惯型：幂等生成未来 14 天实例（每天最多一条，occurrenceOf=goal.id）。"""
    payload = await _read_optional_plan_body(request)
    if isinstance(payload, JSONResponse):
        return payload
    if payload:
        return _unknown_field_response(list(payload))

    root = request_data_root(request)
    now = current_time()
    loaded = load_snapshot(root)
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None
    goal = loaded.snapshot.goals.get(goal_id)
    if goal is None:
        return error_response(404, "goal_not_found", "长期任务不存在。")
    # 期 3.4：归档/已完成目标直接 409（不生成实例、不写库）
    failure = _goal_active_failure(goal)
    if failure is not None:
        return failure
    if goal.kind != "habit":
        return error_response(
            422,
            "goal_not_habit",
            "只有 habit 型长期任务可以生成习惯实例。",
        )

    outcome: dict[str, Any] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        latest = snapshot.goals.get(goal_id)
        if latest is None:
            outcome["error"] = ApiError(404, "goal_not_found", "长期任务不存在。")
            return SKIP_COMMIT  # type: ignore[return-value]
        existing_dates = set(
            existing_task_dates(goal_id, list(snapshot.tasks.values()))
        )
        days = build_occurrence_days(latest, now.date(), existing_dates)
        if not days:
            outcome["created"] = 0
            return SKIP_COMMIT  # type: ignore[return-value]
        source = Source.model_validate(
            build_manual_source(f"习惯：{latest.title}", now)
        )
        new_tasks = [
            Task.model_validate(item)
            for item in build_occurrence_task_payloads(
                latest, days, source.id, now
            )
        ]
        updated = snapshot.add_source(source)
        for task in new_tasks:
            updated = updated.add_task(task)
        outcome["created"] = len(new_tasks)
        return updated

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("POST /goals/occurrences", result)
    if "error" in outcome:
        return api_error_response(outcome["error"])
    return JSONResponse(
        status_code=200, content={"created": int(outcome.get("created", 0))}
    )
