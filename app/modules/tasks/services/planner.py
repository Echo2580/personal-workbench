"""长期任务规划服务（期 3/4/5）：补空缺、习惯实例、进度统计。

规划分两步，**本模块不写库**：

1. ``run_goal_plan`` 计算目标区间内的空缺自然日、调用模型，只产出 drafts；
2. API 层在用户确认后把 drafts 落成带 ``goalId``/``planRevision`` 的 Task。

所有自然日以 Asia/Shanghai 为准；"已有任务落在哪天"统一取 dueTime 优先、其次
startTime（任务单规则）。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping

from pydantic import ValidationError

from app.modules.tasks.domain import Goal, Task, TimeInfo
from app.modules.tasks.services.model_adapter import (
    GoalPlanningModel,
    GoalPlanningRequest,
)

SHANGHAI = timezone(timedelta(hours=8))
TEXT_MIME = "text/plain; charset=utf-8"

# 规划视界：一次最多规划 60 天、最多 120 条草稿（任务单上限）
PLAN_HORIZON_DAYS = 60
PLAN_MAX_DRAFTS = 120
# 习惯实例：未来 14 个自然日（含今天）
OCCURRENCE_HORIZON_DAYS = 14
# 规划任务的默认时刻：模型只给日期时补 20:00（Asia/Shanghai），保证首页/日历
# 按"截止优先、其次开始"稳定归类（期 3.1 验收修正）。
PLAN_DEFAULT_TIME = "20:00:00"

_TIME_KEYS = ("rawExpression", "precision", "resolvedValue", "status")
_NAIVE_DATETIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\Z"
)
_NONE_REMINDER: dict[str, Any] = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": None,
}


class PlanDraftError(Exception):
    """模型输出可解析但规划草稿字段非法 → 502 plan_validation_failed。"""

    def __init__(
        self,
        validation_error: ValidationError | None,
        index: int = 0,
        message: str = "",
        path: str = "",
    ):
        self.validation_error = validation_error
        self.index = index
        self.path = path or f"drafts[{index}]"
        self.message = message or f"draft {index} failed validation"
        super().__init__(self.message)


@dataclass
class PlanDraftValidation:
    """模型任务列表的校验结果：保留的草稿 + 原始条数 + 被丢弃条数。"""

    drafts: list[dict[str, Any]]
    raw_count: int
    dropped: int


@dataclass
class GoalPlanOutcome:
    """一次规划调用的结果；``model_called`` 区分"无缺口直接返回"。"""

    model_called: bool
    drafts: list[dict[str, Any]]
    suggested_target_date: str | None = None
    # 模型返回条数 / 被丢弃条数（期 3.3：前端据此解释"为什么没草稿"）
    raw_count: int = 0
    dropped: int = 0


# --------------------------------------------------------------------------- #
# 自然日与空缺计算
# --------------------------------------------------------------------------- #


def _parse_iso_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def time_info_date(info: TimeInfo | None) -> date | None:
    """已解析的 TimeInfo 折算自然日；待确认/非日期精度返回 None。"""
    if info is None or info.status != "resolved" or info.resolved_value is None:
        return None
    if info.precision == "date":
        return _parse_iso_date(info.resolved_value)
    if info.precision == "datetime":
        return _parse_iso_date(info.resolved_value[:10])
    return None


def task_goal_date(task: Task) -> date | None:
    """任务所属自然日：dueTime 优先，其次 startTime。"""
    for info in (task.due_time, task.start_time):
        resolved = time_info_date(info)
        if resolved is not None:
            return resolved
    return None


def existing_task_dates(goal_id: str, tasks: Iterable[Task]) -> dict[date, list[Task]]:
    """按自然日聚合某个目标的已有任务（用于补空缺与幂等判断）。"""
    grouped: dict[date, list[Task]] = {}
    for task in tasks:
        if task.goal_id != goal_id:
            continue
        day = task_goal_date(task)
        if day is None:
            continue
        grouped.setdefault(day, []).append(task)
    return grouped


def plan_window(goal: Goal, today: date) -> tuple[date, date] | None:
    """规划视界：从 max(今天, startDate) 起最多 60 天，且不越过 targetDate。

    返回 None 表示不再需要规划（目标日期已过 / 目标不完整）。
    """
    if goal.kind != "plan" or goal.target_date is None:
        return None
    start = _parse_iso_date(goal.start_date)
    target = _parse_iso_date(goal.target_date)
    if start is None or target is None:
        return None
    window_start = max(today, start)
    if window_start > target:
        return None
    window_end = min(target, window_start + timedelta(days=PLAN_HORIZON_DAYS - 1))
    return window_start, window_end


def compute_gap_dates(
    goal: Goal,
    tasks: Iterable[Task],
    today: date,
    unavailable: Iterable[date] = (),
) -> list[date]:
    """目标视界内"还没有该目标任务、且不是不可用日"的自然日。"""
    window = plan_window(goal, today)
    if window is None:
        return []
    window_start, window_end = window
    existing = set(existing_task_dates(goal.id, tasks))
    blocked = set(unavailable)
    days: list[date] = []
    cursor = window_start
    while cursor <= window_end:
        if cursor not in existing and cursor not in blocked:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def build_planning_request(
    goal: Goal,
    gaps: list[date],
    tasks: Iterable[Task],
    today: date,
    unavailable: Iterable[date] = (),
) -> GoalPlanningRequest:
    """把目标与空缺日整理成模型输入（目标 + 区间 + 容量 + 不可用日 + 已有任务）。"""
    window = plan_window(goal, today)
    assert window is not None  # 调用方保证 gaps 非空时视界存在
    window_start, window_end = window
    existing_tasks: list[dict[str, str]] = []
    for day, day_tasks in sorted(existing_task_dates(goal.id, tasks).items()):
        if not (window_start <= day <= window_end):
            continue
        for task in day_tasks:
            existing_tasks.append({"date": day.isoformat(), "title": task.title})
    return GoalPlanningRequest(
        goal_id=goal.id,
        title=goal.title,
        description=goal.description,
        constraints=list(goal.constraints or []),
        start_date=goal.start_date,
        target_date=str(goal.target_date),
        daily_capacity=int(goal.daily_capacity or 1),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        gap_dates=[day.isoformat() for day in gaps],
        existing_tasks=existing_tasks,
        unavailable_dates=sorted(day.isoformat() for day in set(unavailable)),
    )


# --------------------------------------------------------------------------- #
# 模型输出 → drafts
# --------------------------------------------------------------------------- #


def _normalise_time(raw: Any, index: int, field: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise PlanDraftError(
            None, index, f"{field} 必须是时间对象或 null", f"drafts[{index}].{field}"
        )
    payload: dict[str, Any] = {key: raw.get(key) for key in _TIME_KEYS}
    # 服务端固定时区，不接受模型提供的值
    payload["timeZone"] = "Asia/Shanghai"
    # 期 3.1：模型给出时刻但漏了时区 → 按 Asia/Shanghai 解释（+08:00）
    resolved = payload.get("resolvedValue")
    if payload.get("precision") == "datetime" and isinstance(resolved, str):
        if _NAIVE_DATETIME_PATTERN.fullmatch(resolved):
            payload["resolvedValue"] = f"{resolved}+08:00"
    try:
        TimeInfo.model_validate(payload)
    except ValidationError as exc:
        raise PlanDraftError(
            exc, index, f"{field} 字段不合法", f"drafts[{index}].{field}"
        ) from exc
    return payload


def _normalise_requirements(raw: Any, index: int) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlanDraftError(
            None, index, "requirements 必须是字符串数组", f"drafts[{index}].requirements"
        )
    normalised: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise PlanDraftError(
                None,
                index,
                "requirements 必须是字符串数组",
                f"drafts[{index}].requirements",
            )
        if item.strip():
            normalised.append(item.strip())
    return normalised


def time_payload_date(payload: Mapping[str, Any] | None) -> date | None:
    """时间载荷折算自然日（date 精度取当天，datetime 取日期部分）。"""
    if payload is None or payload.get("status") != "resolved":
        return None
    resolved = payload.get("resolvedValue")
    precision = payload.get("precision")
    if precision == "date":
        return _parse_iso_date(resolved)
    if precision == "datetime" and isinstance(resolved, str):
        return _parse_iso_date(resolved[:10])
    return None


def is_concrete_datetime(payload: Mapping[str, Any] | None) -> bool:
    """时间载荷是否已带具体钟点（resolved + datetime 精度 + 时刻值）。"""
    if not payload:
        return False
    return bool(
        payload.get("status") == "resolved"
        and payload.get("precision") == "datetime"
        and isinstance(payload.get("resolvedValue"), str)
        and "T" in str(payload["resolvedValue"])
    )


def planned_due_time(planned: date, raw_expression: str | None) -> dict[str, Any]:
    """规划任务默认截止时刻：plannedDate 20:00 +08:00（期 3.1 规则）。"""
    return {
        "rawExpression": raw_expression,
        "precision": "datetime",
        "resolvedValue": f"{planned.isoformat()}T{PLAN_DEFAULT_TIME}+08:00",
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def normalise_plan_times(
    start_time: dict[str, Any] | None,
    due_time: dict[str, Any] | None,
    planned: date | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """保证规划任务带具体时刻（期 3.1 验收修正）。

    - 已有具体 datetime：原样保留（两个都具体则都保留）；
    - 只有一个具体 datetime：保留它，另一个（日期精度/为空）置 null，避免双时间；
    - 都没有具体时刻：补 ``dueTime = planned 20:00 +08:00``（precision=datetime、
      status=resolved；rawExpression 保留原值，否则用「规划：YYYY-MM-DD」），
      ``startTime`` 置 null。
    ``planned`` 未知（无法确定自然日）时不补充，原样返回。
    """
    concrete_start = is_concrete_datetime(start_time)
    concrete_due = is_concrete_datetime(due_time)
    if concrete_start and concrete_due:
        return start_time, due_time
    if concrete_start:
        return start_time, None
    if concrete_due:
        return None, due_time
    if planned is None:
        return start_time, due_time
    raw_expression: str | None = None
    for payload in (due_time, start_time):
        if payload is not None and isinstance(payload.get("rawExpression"), str):
            raw_expression = str(payload["rawExpression"])
            break
    if raw_expression is None:
        raw_expression = f"规划：{planned.isoformat()}"
    return None, planned_due_time(planned, raw_expression)


def _planned_date_from_raw(
    raw: Mapping[str, Any],
    index: int,
    start_payload: dict[str, Any] | None,
    due_payload: dict[str, Any] | None,
) -> date | None:
    """任务的自然日：plannedDate → dueTime → startTime（期 3.3 优先级）。"""
    planned_raw = raw.get("plannedDate")
    if planned_raw is not None:
        planned = _parse_iso_date(planned_raw)
        if planned is None:
            raise PlanDraftError(
                None,
                index,
                "plannedDate 必须是真实 YYYY-MM-DD",
                f"drafts[{index}].plannedDate",
            )
        return planned
    return time_payload_date(due_payload) or time_payload_date(start_payload)


def validate_plan_tasks(
    raw_tasks: list[Any],
    gaps: list[date],
    daily_capacity: int,
) -> PlanDraftValidation:
    """校验并规范化模型返回的任务列表；只保留落在空缺日的任务。

    - 任一任务字段非法 → PlanDraftError（整轮失败，不部分接受）；
    - 日期优先级：``plannedDate`` → ``dueTime`` → ``startTime``；
    - 日期不在空缺日 / 三者均无日期 / 超过每日容量 → 计入 ``dropped``；
    - 每天最多 ``daily_capacity`` 条，总量最多 ``PLAN_MAX_DRAFTS`` 条。
    """
    gap_set = set(gaps)
    capacity = max(1, daily_capacity)
    per_day: dict[date, int] = {}
    drafts: list[dict[str, Any]] = []
    raw_count = len(raw_tasks)
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, Mapping):
            raise PlanDraftError(None, index, "任务必须是 JSON 对象")
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            raise PlanDraftError(
                None, index, "title 必须是非空字符串", f"drafts[{index}].title"
            )
        start_payload = _normalise_time(raw.get("startTime"), index, "startTime")
        due_payload = _normalise_time(raw.get("dueTime"), index, "dueTime")
        requirements = _normalise_requirements(raw.get("requirements"), index)

        planned = _planned_date_from_raw(raw, index, start_payload, due_payload)
        if planned is None or planned not in gap_set:
            continue
        if per_day.get(planned, 0) >= capacity:
            continue
        # 期 3.1：缺时刻的任务补 dueTime=planned 20:00，保证日历/首页归类稳定
        start_payload, due_payload = normalise_plan_times(
            start_payload, due_payload, planned
        )
        per_day[planned] = per_day.get(planned, 0) + 1
        drafts.append(
            {
                "draftId": str(uuid.uuid4()),
                "plannedDate": planned.isoformat(),
                "title": title.strip(),
                "startTime": start_payload,
                "dueTime": due_payload,
                "requirements": requirements,
            }
        )
        if len(drafts) >= PLAN_MAX_DRAFTS:
            break
    drafts.sort(key=lambda draft: draft["plannedDate"])
    return PlanDraftValidation(
        drafts=drafts,
        raw_count=raw_count,
        dropped=raw_count - len(drafts),
    )


def run_goal_plan(
    goal: Goal,
    tasks: Iterable[Task],
    model: GoalPlanningModel,
    today: date,
    unavailable: Iterable[date] = (),
) -> GoalPlanOutcome:
    """计算空缺 → （有缺口才）调用模型 → 返回 drafts；任何失败都不写库。"""
    unavailable_set = set(unavailable)
    task_list = list(tasks)
    gaps = compute_gap_dates(goal, task_list, today, unavailable_set)
    if not gaps:
        # 无缺口：不调模型、不消耗规划轮次
        return GoalPlanOutcome(model_called=False, drafts=[])

    request = build_planning_request(
        goal, gaps, task_list, today, unavailable_set
    )
    result = model.plan_goal(request)  # 模型异常向上抛给 API 分型

    suggested = result.target_date
    if suggested is not None and _parse_iso_date(suggested) is None:
        raise PlanDraftError(
            None, 0, "targetDate 必须是真实 YYYY-MM-DD 或 null", "suggestedTargetDate"
        )
    drafts = validate_plan_tasks(
        result.tasks, gaps, int(goal.daily_capacity or 1)
    )
    return GoalPlanOutcome(
        model_called=True,
        drafts=drafts.drafts,
        suggested_target_date=suggested,
        raw_count=drafts.raw_count,
        dropped=drafts.dropped,
    )


# --------------------------------------------------------------------------- #
# 落库用 Task / Source 构造
# --------------------------------------------------------------------------- #


def build_manual_source(original_text: str, now: datetime) -> dict[str, Any]:
    """为规划/习惯批次生成 kind="manual" 的来源（不新增 Source.kind）。"""
    return {
        "id": str(uuid.uuid4()),
        "kind": "manual",
        "mimeType": TEXT_MIME,
        "fileName": None,
        "messageDate": now.date().isoformat(),
        "importedAt": now.isoformat(),
        "contentSha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
        "originalText": original_text,
        "relativePath": None,
    }


def _base_task_payload(
    *,
    draft_id: str,
    source_id: str,
    title: str,
    start_time: dict[str, Any] | None,
    due_time: dict[str, Any] | None,
    requirements: list[str],
    goal_id: str,
    occurrence_of: str | None,
    plan_revision: int | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "draftId": draft_id,
        "sourceId": source_id,
        "goalId": goal_id,
        "occurrenceOf": occurrence_of,
        "planRevision": plan_revision,
        "title": title,
        "startTime": start_time,
        "dueTime": due_time,
        "requirements": list(requirements),
        "applicability": {"text": None, "status": "not_stated"},
        # 任务原文即标题：规划/习惯任务不需要待核对原文片段
        "sourceExcerpt": title,
        "reviewIssues": [],
        "status": "open",
        "reminder": {**_NONE_REMINDER, "revision": str(uuid.uuid4())},
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
    }


def build_plan_task_payload(
    *,
    draft_id: str,
    title: str,
    start_time: dict[str, Any] | None,
    due_time: dict[str, Any] | None,
    requirements: list[str],
    planned_date: date | None,
    goal: Goal,
    source_id: str,
    plan_revision: int | None,
    now: datetime,
) -> dict[str, Any]:
    """把确认后的规划草稿构造为待保存 Task 载荷（带 goalId/planRevision）。

    期 3.1：缺时刻的草稿统一补 ``dueTime=plannedDate 20:00+08:00``，保证落库
    任务始终带具体时刻（首页/日历按截止优先归类）。
    """
    start_time, due_time = normalise_plan_times(start_time, due_time, planned_date)
    return _base_task_payload(
        draft_id=draft_id,
        source_id=source_id,
        title=title,
        start_time=start_time,
        due_time=due_time,
        requirements=requirements,
        goal_id=goal.id,
        occurrence_of=None,
        plan_revision=plan_revision,
        now=now,
    )


# --------------------------------------------------------------------------- #
# 习惯实例（期 4）
# --------------------------------------------------------------------------- #


def build_occurrence_days(
    goal: Goal, today: date, existing_dates: set[date]
) -> list[date]:
    """未来 14 个自然日里尚未生成实例、且符合重现规则的日期。"""
    if goal.kind != "habit" or goal.recurrence is None:
        return []
    start = _parse_iso_date(goal.start_date)
    weekdays = set(goal.recurrence.weekdays or [])
    days: list[date] = []
    for offset in range(OCCURRENCE_HORIZON_DAYS):
        day = today + timedelta(days=offset)
        if start is not None and day < start:
            continue
        if goal.recurrence.freq == "weekly" and day.isoweekday() not in weekdays:
            continue
        if day in existing_dates:
            continue
        days.append(day)
    return days


def build_occurrence_task_payloads(
    goal: Goal,
    days: list[date],
    source_id: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """按重现规则构造习惯实例：occurrenceOf=goal.id，每天最多一条。

    期 3.2：实例的 ``dueTime`` 一律为具体时刻（``recurrence.time``，未配置时用
    规划默认 20:00，+08:00；precision=datetime、status=resolved），``startTime``
    恒为 null；``durationMinutes`` 只写进执行要求文案，不改时间字段。
    """
    recurrence = goal.recurrence
    assert recurrence is not None
    clock = recurrence.time if recurrence.time is not None else PLAN_DEFAULT_TIME[:5]
    hour, minute = (int(part) for part in clock.split(":"))
    requirements = (
        [f"约 {recurrence.duration_minutes} 分钟"]
        if recurrence.duration_minutes is not None
        else []
    )
    payloads: list[dict[str, Any]] = []
    for day in days:
        moment = datetime.combine(day, time(hour, minute), tzinfo=SHANGHAI)
        due_time = {
            "rawExpression": (
                recurrence.time
                if recurrence.time is not None
                else f"规划：{day.isoformat()}"
            ),
            "precision": "datetime",
            "resolvedValue": moment.isoformat(),
            "timeZone": "Asia/Shanghai",
            "status": "resolved",
        }
        payloads.append(
            _base_task_payload(
                draft_id=str(uuid.uuid4()),
                source_id=source_id,
                title=goal.title,
                start_time=None,
                due_time=due_time,
                requirements=list(requirements),
                goal_id=goal.id,
                occurrence_of=goal.id,
                plan_revision=None,
                now=now,
            )
        )
    return payloads


# --------------------------------------------------------------------------- #
# 进度（期 5）
# --------------------------------------------------------------------------- #


def goal_progress(goal_id: str, tasks: Iterable[Task], today: date) -> dict[str, int]:
    """按 goalId 统计 total / completed / overdue（逾期=未完成且日期早于今天）。"""
    scoped = [task for task in tasks if task.goal_id == goal_id]
    completed = sum(1 for task in scoped if task.status == "completed")
    overdue = 0
    for task in scoped:
        if task.status != "open":
            continue
        day = task_goal_date(task)
        if day is not None and day < today:
            overdue += 1
    return {"total": len(scoped), "completed": completed, "overdue": overdue}
