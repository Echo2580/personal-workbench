"""手动新建待办（工作台清单页入口）。

与「通知提取 → 确认」链路保持同一套校验与提醒解析，区别只在于来源：
这里生成一条 ``kind="manual"`` 的 Source，originalText 保存用户输入的原话，
因此任务详情的「来源回看」仍然可用，也不会伪装成通知截图。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.tasks.api import ApiError, FieldError
from app.modules.tasks.api.dto import (
    ApplicabilityInput,
    ReminderInput,
    TimeInfoInput,
    reminder_candidate,
    resolve_reminder,
    time_info_payload,
    validation_error_to_api_error,
)
from app.modules.tasks.domain import Source, Task
from app.modules.tasks.storage import commit

TEXT_MIME = "text/plain; charset=utf-8"
MAX_TITLE = 200


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ManualTaskInput(_StrictModel):
    """POST /tasks 的请求体：标题必填，其余可选（八可写键的子集）。"""

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    start_time: TimeInfoInput | None = Field(default=None, alias="startTime")
    due_time: TimeInfoInput | None = Field(default=None, alias="dueTime")
    requirements: list[str] = Field(default_factory=list)
    applicability: ApplicabilityInput | None = None
    reminder: ReminderInput | None = None
    note: str | None = None


@dataclass
class ManualOutcome:
    status_code: int
    body: dict[str, Any] | None = None
    error: ApiError | None = None


def _bad_request(message: str, field: str | None = None) -> ManualOutcome:
    return ManualOutcome(
        400,
        error=ApiError(
            400,
            "invalid_request",
            message,
            [FieldError(field, "invalid", message)] if field else [],
        ),
    )


def _field_error(exc: ValidationError, prefix: str = "") -> ManualOutcome:
    api_error = validation_error_to_api_error(exc)
    if prefix:
        for item in api_error.field_errors:
            item.field = f"{prefix}.{item.field}" if item.field else prefix
    return ManualOutcome(api_error.status_code, error=api_error)


def _build_source(original_text: str, now: datetime) -> Source:
    return Source.model_validate(
        {
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
    )


def create_manual_task(
    root: Path, payload: dict[str, Any], now: datetime
) -> ManualOutcome:
    unknown = [key for key in payload if key not in ManualTaskInput.model_fields and key not in _ALIASES]
    if unknown:
        return ManualOutcome(
            400,
            error=ApiError(
                400,
                "invalid_request",
                "包含不可写或未知字段。",
                [FieldError(key, "unknown_field", "该字段不可写或不存在。") for key in unknown],
            ),
        )

    try:
        task_input = ManualTaskInput.model_validate(payload)
    except ValidationError as exc:
        return _field_error(exc)

    title = task_input.title.strip()
    if not title:
        return ManualOutcome(
            422,
            error=ApiError(
                422,
                "task_validation_failed",
                "任务标题不能为空。",
                [FieldError("title", "blank", "任务标题不能为空。")],
            ),
        )

    original_text = (task_input.note or title).strip()
    source = _build_source(original_text, now)
    timestamp = now.isoformat()

    task_payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "draftId": str(uuid.uuid4()),
        "sourceId": source.id,
        "title": title,
        "startTime": (
            None if task_input.start_time is None else time_info_payload(task_input.start_time)
        ),
        "dueTime": (
            None if task_input.due_time is None else time_info_payload(task_input.due_time)
        ),
        "requirements": [item for item in task_input.requirements if item.strip()],
        "applicability": (
            {"text": None, "status": "not_stated"}
            if task_input.applicability is None
            else {"text": task_input.applicability.text, "status": task_input.applicability.status}
        ),
        # 手动任务的"原文"就是用户输入本身（note 优先，否则用标题），
        # 这样来源回看有内容，也不会误触发 source_excerpt_missing 待确认。
        "sourceExcerpt": original_text,
        "reviewIssues": [],
        "status": "open",
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }

    if task_input.reminder is None:
        task_payload["reminder"] = reminder_candidate(
            ReminderInput(
                mode="none",
                requestedAt=None,
                relativeTo=None,
                offsetMinutes=None,
            ),
            str(uuid.uuid4()),
        )
        resolve_reminder(task_payload["reminder"], task_payload, "open")
    else:
        candidate = reminder_candidate(task_input.reminder, str(uuid.uuid4()))
        if candidate["mode"] == "manual" and candidate["requestedAt"] is not None:
            try:
                requested = datetime.fromisoformat(str(candidate["requestedAt"]))
            except ValueError:
                requested = None
            if requested is not None and requested < now:
                return ManualOutcome(
                    422,
                    error=ApiError(
                        422,
                        "reminder_time_in_past",
                        "提醒时刻已经过去。",
                        [FieldError("reminder.requestedAt", "in_past", "提醒时刻已经过去。")],
                    ),
                )
        failure = resolve_reminder(candidate, task_payload, "open")
        if failure is not None:
            return ManualOutcome(failure.status_code, error=failure)
        task_payload["reminder"] = candidate

    try:
        task = Task.model_validate(task_payload)
    except ValidationError as exc:
        return _field_error(exc)

    def mutate(snapshot):
        return snapshot.add_source(source).add_task(task)

    result = commit(root, mutate)
    if result.error is not None:
        code = str(result.error.get("code", "storage_write_failed"))
        return ManualOutcome(500, error=ApiError(500, code, str(result.error.get("message", "存储操作失败。"))))

    return ManualOutcome(
        201,
        body={
            "task": task.model_dump(mode="json", by_alias=True),
            "source": source.model_dump(mode="json", by_alias=True),
        },
    )


_ALIASES = {
    "title",
    "startTime",
    "dueTime",
    "requirements",
    "applicability",
    "reminder",
    "note",
}
