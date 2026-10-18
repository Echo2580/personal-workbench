"""Task CRUD endpoints (契约 §4): list, detail, PATCH, DELETE."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any, Set

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

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
from app.modules.tasks.domain import Task, to_source_metadata
from app.modules.tasks.services.manual import create_manual_task
from app.modules.tasks.storage import SKIP_COMMIT, Snapshot, commit, load_snapshot


router = APIRouter()

# 时钟统一由 app.modules.tasks.api.current_time 提供（T16 项①上移到公共处）

# §4.2 PATCH 可写键（八个）
WRITABLE_KEYS: tuple[str, ...] = (
    "title",
    "startTime",
    "dueTime",
    "requirements",
    "applicability",
    "sourceExcerpt",
    "reminder",
    "status",
)
# 只有这三个允许显式 null 清空
NULL_ALLOWED: frozenset[str] = frozenset({"startTime", "dueTime", "sourceExcerpt"})

LIST_STATUSES: frozenset[str] = frozenset({"open", "completed", "all"})

from app.modules.tasks.api.dto import (
    ApplicabilityInput,
    ApplicabilityStatus,
    PatchTaskBody,
    ReminderInput,
    ReminderMode,
    RelativeTo,
    TaskStatus,
    TimeInfoInput,
    TimePrecision,
    TimeStatus,
    field_path as _field_path,
    has_pending_confirmation as _has_pending_confirmation,
    reminder_candidate as _reminder_candidate,
    resolve_reminder as _resolve_reminder,
    time_info_payload as _time_info_payload,
    validation_error_to_api_error as _validation_error_to_api_error,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _build_patched_task(
    current: Task,
    body: PatchTaskBody,
    present: set[str],
    now: datetime,
) -> tuple[Task | None, ApiError | None]:
    """Apply §4.2/§3.5 to a task and return the validated replacement."""
    merged = current.model_dump(mode="json", by_alias=True)

    if "title" in present:
        merged["title"] = body.title
    if "requirements" in present:
        merged["requirements"] = list(body.requirements or [])
    if "sourceExcerpt" in present:
        merged["sourceExcerpt"] = body.source_excerpt
    if "startTime" in present:
        merged["startTime"] = (
            None if body.start_time is None else _time_info_payload(body.start_time)
        )
    if "dueTime" in present:
        merged["dueTime"] = (
            None if body.due_time is None else _time_info_payload(body.due_time)
        )
    if "applicability" in present:
        assert body.applicability is not None  # null already rejected
        merged["applicability"] = {
            "text": body.applicability.text,
            "status": body.applicability.status,
        }
    if "status" in present:
        merged["status"] = body.status

    current_reminder = current.reminder
    reminder_explicit = "reminder" in present
    structural_change = bool(
        present & {"startTime", "dueTime", "applicability", "status"}
    )

    if reminder_explicit:
        assert body.reminder is not None  # null already rejected
        # 显式提交 reminder：一律更换版本并清空 acknowledgedAt
        candidate = _reminder_candidate(body.reminder, str(uuid.uuid4()))
        if candidate["mode"] == "manual" and candidate["requestedAt"] is not None:
            try:
                requested = datetime.fromisoformat(str(candidate["requestedAt"]))
            except ValueError:
                requested = None
            if requested is not None and requested < now:
                return None, ApiError(
                    422,
                    "reminder_time_in_past",
                    "提醒时刻已经过去。",
                    [FieldError("reminder.requestedAt", "in_past", "提醒时刻已经过去")],
                )
        failure = _resolve_reminder(candidate, merged, str(merged["status"]))
        if failure is not None:
            return None, failure
        merged["reminder"] = candidate
    elif structural_change and current_reminder.state in ("scheduled", "blocked"):
        # 未显式提交 reminder：仅原 scheduled/blocked 更换版本并重算
        candidate = current_reminder.model_dump(mode="json", by_alias=True)
        candidate["revision"] = str(uuid.uuid4())
        candidate["acknowledgedAt"] = None
        failure = _resolve_reminder(candidate, merged, str(merged["status"]))
        if failure is not None:
            return None, failure
        merged["reminder"] = candidate
    # 其他情况：reminder 及其版本/状态原样保留（终态不自动重启）

    merged["updatedAt"] = now.isoformat()

    try:
        # reviewIssues 由 Task 模型按最终字段重算
        return Task.model_validate(merged), None
    except ValidationError as exc:
        return None, _validation_error_to_api_error(exc)


def _parse_patch_payload(
    payload: dict[str, Any],
) -> tuple[tuple[PatchTaskBody, set[str]] | None, ApiError | None]:
    unknown = [key for key in payload if key not in WRITABLE_KEYS]
    if unknown:
        return None, ApiError(
            400,
            "invalid_request",
            "包含不可写或未知字段。",
            [
                FieldError(key, "unknown_field", "该字段不可写或不存在。")
                for key in unknown
            ],
        )

    try:
        body = PatchTaskBody.model_validate(payload)
    except ValidationError as exc:
        return None, _validation_error_to_api_error(exc)

    present = set(payload)
    for key in present:
        if key not in NULL_ALLOWED and payload[key] is None:
            return None, ApiError(
                422,
                "task_validation_failed",
                f"{key} 不允许为 null。",
                [FieldError(key, "null_not_allowed", "该字段不允许为 null。")],
            )
    return (body, present), None


async def _read_json_object(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - any parse failure is a 400
        return error_response(400, "invalid_request", "请求体必须是合法 JSON。")
    if not isinstance(payload, dict):
        return error_response(400, "invalid_request", "请求体必须是 JSON 对象。")
    if not payload:
        return error_response(400, "invalid_request", "请求体不能为空对象。")
    return payload


# --------------------------------------------------------------------------- #
# 期 2：列表过滤 from/to（按 dueTime 或 startTime 的日期，含边界）与 goalId
# --------------------------------------------------------------------------- #

_DATE_PARAM_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_GOAL_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


def _parse_date_param(value: str | None, field: str) -> tuple[date | None, FieldError | None]:
    if value is None:
        return None, None
    if not _DATE_PARAM_PATTERN.fullmatch(value):
        return None, FieldError(field, "invalid_date", "日期必须使用 YYYY-MM-DD。")
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, FieldError(field, "invalid_date", "日期必须是真实日历日期。")


def _resolved_date(time_info) -> date | None:
    """把已解析的 startTime/dueTime 折算成自然日；待确认/相对时间不参与过滤。"""
    if time_info is None or time_info.status != "resolved":
        return None
    if time_info.resolved_value is None:
        return None
    if time_info.precision == "date":
        raw = time_info.resolved_value
    elif time_info.precision == "datetime":
        raw = time_info.resolved_value[:10]
    else:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _task_in_date_range(
    task: Task, date_from: date | None, date_to: date | None
) -> bool:
    """dueTime 或 startTime 任一落在 [from, to]（含边界）即命中。"""
    candidates = [
        moment
        for moment in (_resolved_date(task.due_time), _resolved_date(task.start_time))
        if moment is not None
    ]
    for moment in candidates:
        if date_from is not None and moment < date_from:
            continue
        if date_to is not None and moment > date_to:
            continue
        return True
    return False


def _task_goal_id(task: Task) -> str | None:
    """期 3 起 Task.goalId 已是正式字段；通知/手动任务为 null。"""
    return task.goal_id


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str = "open",
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    goal_id: str | None = Query(default=None, alias="goalId"),
) -> JSONResponse:
    if status not in LIST_STATUSES:
        return error_response(
            400,
            "invalid_status",
            "status 必须是 open、completed 或 all。",
            [FieldError("status", "invalid_enum", "只接受 open/completed/all。")],
        )

    filter_errors: list[FieldError] = []
    date_from, failure = _parse_date_param(from_date, "from")
    if failure is not None:
        filter_errors.append(failure)
    date_to, failure = _parse_date_param(to_date, "to")
    if failure is not None:
        filter_errors.append(failure)
    if goal_id is not None and not _GOAL_ID_PATTERN.fullmatch(goal_id):
        filter_errors.append(
            FieldError("goalId", "invalid_uuid", "goalId 必须是标准 UUID。")
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        filter_errors.append(
            FieldError("from", "invalid_range", "from 不能晚于 to。")
        )
    if filter_errors:
        return error_response(
            400,
            "invalid_filter",
            "列表过滤参数不合法。",
            filter_errors,
        )

    loaded = load_snapshot(request_data_root(request))
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None

    tasks = list(loaded.snapshot.tasks.values())
    if status != "all":
        tasks = [task for task in tasks if task.status == status]
    if date_from is not None or date_to is not None:
        tasks = [
            task for task in tasks if _task_in_date_range(task, date_from, date_to)
        ]
    if goal_id is not None:
        tasks = [task for task in tasks if _task_goal_id(task) == goal_id]

    # createdAt 倒序；同一时刻按 id 升序（两次稳定排序）
    tasks.sort(key=lambda task: task.id)
    tasks.sort(key=lambda task: task.created_at, reverse=True)

    return JSONResponse(
        status_code=200,
        content={
            "tasks": [
                task.model_dump(mode="json", by_alias=True) for task in tasks
            ]
        },
    )


@router.post("/tasks", status_code=201)
async def create_task(request: Request) -> JSONResponse:
    """手动新建待办（来源 kind=manual，无需通知）。"""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return error_response(400, "invalid_request", "请求体必须是合法 JSON。")
    if not isinstance(payload, dict):
        return error_response(400, "invalid_request", "请求体必须是 JSON 对象。")
    outcome = create_manual_task(request_data_root(request), payload, current_time())
    if outcome.error is not None:
        return api_error_response(outcome.error)
    return JSONResponse(status_code=outcome.status_code, content=outcome.body or {})


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> JSONResponse:
    loaded = load_snapshot(request_data_root(request))
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None

    task = loaded.snapshot.tasks.get(task_id)
    if task is None:
        return error_response(404, "task_not_found", "任务不存在。")

    source = loaded.snapshot.sources.get(task.source_id)
    if source is None:
        # 快照内引用缺失属数据完整性问题，按存储读取错误上报
        return error_response(
            500, "storage_read_failed", "任务引用的来源在快照中不存在。"
        )

    return JSONResponse(
        status_code=200,
        content={
            "task": task.model_dump(mode="json", by_alias=True),
            "source": to_source_metadata(source).model_dump(
                mode="json", by_alias=True
            ),
        },
    )


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: str, request: Request) -> JSONResponse:
    payload = await _read_json_object(request)
    if isinstance(payload, JSONResponse):
        return payload

    parsed, failure = _parse_patch_payload(payload)
    if failure is not None:
        return api_error_response(failure)
    assert parsed is not None
    body, present = parsed

    root = request_data_root(request)
    now = current_time()

    loaded = load_snapshot(root)
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None
    current = loaded.snapshot.tasks.get(task_id)
    if current is None:
        return error_response(404, "task_not_found", "任务不存在。")

    # 先在锁外构建一次，非法请求不触发任何写入
    probe, failure = _build_patched_task(current, body, present, now)
    if failure is not None:
        return api_error_response(failure)
    assert probe is not None

    outcome: dict[str, ApiError] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        latest = snapshot.tasks.get(task_id)
        if latest is None:
            outcome["error"] = ApiError(404, "task_not_found", "任务不存在。")
            return snapshot
        replacement, failure = _build_patched_task(latest, body, present, now)
        if failure is not None:
            outcome["error"] = failure
            return snapshot
        assert replacement is not None
        return Snapshot(
            schema_version=snapshot.schema_version,
            sources=snapshot.sources,
            tasks={**snapshot.tasks, task_id: replacement},
            goals=snapshot.goals,
            confirmed_draft_sets=snapshot.confirmed_draft_sets,
        )

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("PATCH /tasks", result)
    if "error" in outcome:
        return api_error_response(outcome["error"])

    assert result.snapshot is not None
    task = result.snapshot.tasks.get(task_id)
    assert task is not None
    return JSONResponse(
        status_code=200,
        content={"task": task.model_dump(mode="json", by_alias=True)},
    )


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request) -> Response:
    root = request_data_root(request)

    def _mutate(snapshot: Snapshot) -> Snapshot:
        # 项③：任务不存在（含重复删除）→ 确知无变化，跳过写盘
        if task_id not in snapshot.tasks:
            return SKIP_COMMIT  # type: ignore[return-value]
        remaining = {
            key: value
            for key, value in snapshot.tasks.items()
            if key != task_id
        }
        return Snapshot(
            schema_version=snapshot.schema_version,
            sources=snapshot.sources,
            tasks=remaining,
            goals=snapshot.goals,
            confirmed_draft_sets=snapshot.confirmed_draft_sets,
        )

    result = commit(root, _mutate)
    if result.error is not None:
        return storage_error_response(result.error)
    note_commit_warning("DELETE /tasks", result)
    # 重复删除仍是 204；来源不随任务删除
    return Response(status_code=204)
