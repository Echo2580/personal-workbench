"""公共 §4.2 输入 DTO 与错误映射 helper（T16 项①：从 app/api/tasks.py 抽出）。

本模块只做"搬家"，定义与 tasks.py 中原实现逐字一致，供 tasks / confirmation /
extractions 统一导入，消除跨模块私有名依赖。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.tasks.api import ApiError, FieldError


TaskStatus = Literal["open", "completed"]
TimePrecision = Literal["datetime", "date", "day_part", "relative", "unknown"]
TimeStatus = Literal["resolved", "needs_confirmation"]
ApplicabilityStatus = Literal["not_stated", "confirmed", "needs_confirmation"]
ReminderMode = Literal["none", "manual", "relative"]
RelativeTo = Literal["start", "due"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TimeInfoInput(_StrictModel):
    """§4.2 TimeInfoInput：四键必填，timeZone 由服务端固定，不接受客户端提交。"""

    raw_expression: str | None = Field(alias="rawExpression")
    precision: TimePrecision
    resolved_value: str | None = Field(alias="resolvedValue")
    status: TimeStatus


class ApplicabilityInput(_StrictModel):
    """§4.2 ApplicabilityInput：两键必填。"""

    text: str | None
    status: ApplicabilityStatus


class ReminderInput(_StrictModel):
    """§4.2 ReminderInput：四键必填；scheduledAt/state/acknowledgedAt/revision 为只读。"""

    mode: ReminderMode
    requested_at: str | None = Field(alias="requestedAt")
    relative_to: RelativeTo | None = Field(alias="relativeTo")
    offset_minutes: int | None = Field(alias="offsetMinutes")


class PatchTaskBody(_StrictModel):
    """§4.2 PATCH 顶层：八个可写键，全部可选（省略=保持原值）。"""

    title: str | None = None
    start_time: TimeInfoInput | None = Field(default=None, alias="startTime")
    due_time: TimeInfoInput | None = Field(default=None, alias="dueTime")
    requirements: list[str] | None = None
    applicability: ApplicabilityInput | None = None
    source_excerpt: str | None = Field(default=None, alias="sourceExcerpt")
    reminder: ReminderInput | None = None
    status: TaskStatus | None = None


def _camel(name: str) -> str:
    if "_" not in name:
        return name
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def field_path(loc: tuple[Any, ...]) -> str:
    return ".".join(_camel(str(part)) for part in loc)


def validation_error_to_api_error(
    exc: ValidationError, *, prefix: str = ""
) -> ApiError:
    """Map a pydantic ValidationError onto §4.2/§5.

    extra_forbidden (unknown / read-only key) → 400 invalid_request;
    every other shape problem (missing key, wrong type, illegal null,
    combination failure) → 422 task_validation_failed.
    """
    field_errors: list[FieldError] = []
    has_extra = False
    for err in exc.errors():
        location = field_path(tuple(err.get("loc", ())))
        if prefix:
            location = f"{prefix}.{location}" if location else prefix
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
        return ApiError(
            400,
            "invalid_request",
            "包含不可写或未知字段。",
            field_errors,
        )
    return ApiError(422, "task_validation_failed", "任务字段校验失败。", field_errors)


def time_info_payload(dto: TimeInfoInput) -> dict[str, Any]:
    return {
        "rawExpression": dto.raw_expression,
        "precision": dto.precision,
        "resolvedValue": dto.resolved_value,
        "timeZone": "Asia/Shanghai",
        "status": dto.status,
    }


def reminder_candidate(dto: ReminderInput, revision: str) -> dict[str, Any]:
    return {
        "mode": dto.mode,
        "requestedAt": dto.requested_at,
        "scheduledAt": None,
        "relativeTo": dto.relative_to,
        "offsetMinutes": dto.offset_minutes,
        "state": "not_set",
        "acknowledgedAt": None,
        "revision": revision,
    }


def has_pending_confirmation(fields: dict[str, Any]) -> bool:
    applicability = fields.get("applicability") or {}
    if applicability.get("status") == "needs_confirmation":
        return True
    for key in ("startTime", "dueTime"):
        info = fields.get(key)
        if isinstance(info, dict) and info.get("status") == "needs_confirmation":
            return True
    return False


def resolve_reminder(
    candidate: dict[str, Any],
    fields: dict[str, Any],
    task_status: str,
) -> ApiError | None:
    """Derive scheduledAt/state for a reminder (§3.5 validity conditions).

    Mutates ``candidate`` in place. Returns an ApiError only for arithmetic
    overflow, which maps to 422 rather than an unhandled exception.
    """
    mode = candidate["mode"]
    if mode == "none":
        candidate["state"] = "not_set"
        candidate["scheduledAt"] = None
        return None

    # 完成任务的未触发提醒转为 cancelled，不自动重启
    if task_status == "completed":
        candidate["state"] = "cancelled"
        candidate["scheduledAt"] = None
        return None

    def _blocked() -> None:
        candidate["state"] = "blocked"
        candidate["scheduledAt"] = None

    if has_pending_confirmation(fields):
        _blocked()
        return None

    if mode == "manual":
        if candidate["requestedAt"] is None:
            _blocked()
        else:
            candidate["state"] = "scheduled"
            candidate["scheduledAt"] = candidate["requestedAt"]
        return None

    # relative：基准必须是 resolved datetime
    relative_to = candidate["relativeTo"]
    offset = candidate["offsetMinutes"]
    if relative_to not in ("start", "due") or not isinstance(offset, int) or isinstance(
        offset, bool
    ) or offset <= 0:
        _blocked()
        return None

    reference = fields.get("startTime" if relative_to == "start" else "dueTime")
    if (
        not isinstance(reference, dict)
        or reference.get("status") != "resolved"
        or reference.get("precision") != "datetime"
        or not reference.get("resolvedValue")
    ):
        _blocked()
        return None

    try:
        base = datetime.fromisoformat(str(reference["resolvedValue"]))
        scheduled = base - timedelta(minutes=offset)
    except (ValueError, OverflowError):
        return ApiError(
            422,
            "task_validation_failed",
            "提醒时间计算失败。",
            [FieldError("reminder.scheduledAt", "invalid", "提醒时间计算失败")],
        )

    candidate["state"] = "scheduled"
    candidate["scheduledAt"] = scheduled.isoformat()
    return None
