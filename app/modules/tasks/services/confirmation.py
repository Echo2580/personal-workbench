"""Confirmation service: idempotent, all-or-nothing batch save (T07).

Reuses the §4.2 input DTOs and reminder resolution from app.modules.tasks.api.tasks so that
PATCH and confirm apply exactly the same rules (T07 计划 "error helper 复用").
app/api/tasks.py is a frozen T06 baseline, so this module imports its helpers
rather than duplicating them; consolidating them into a shared DTO module is a
follow-up refactor.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.tasks.api import ApiError, FieldError, note_commit_warning
from app.modules.tasks.api.dto import (
    ApplicabilityInput,
    ReminderInput,
    TimeInfoInput,
    field_path as _field_path,
    reminder_candidate as _reminder_candidate,
    resolve_reminder as _resolve_reminder,
    time_info_payload as _time_info_payload,
    validation_error_to_api_error as _validation_error_to_api_error,
)
from app.modules.tasks.domain import Source, Task, to_source_metadata
from app.modules.tasks.services.extraction import DraftSetCache, DraftSetCacheEntry
from app.modules.tasks.storage import Snapshot, commit, load_snapshot


CONFIRM_ROOT_KEYS: tuple[str, ...] = ("source", "confirmedTasks")
TEXT_MIME = "text/plain; charset=utf-8"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceConfirmationInput(_StrictModel):
    """§4.2 SourceConfirmationInput：八键必填。

    messageDate/fileName 可 null；originalText 按契约 §4.2：text 时非空、
    image 时为 null（T11 支持图片确认，故改为可空；text 的非空校验在
    _validate_source_input 中显式执行，行为与 T06 一致）。
    """

    id: str
    kind: Literal["text", "image"]
    original_text: str | None = Field(alias="originalText")
    message_date: str | None = Field(alias="messageDate")
    imported_at: str = Field(alias="importedAt")
    mime_type: str = Field(alias="mimeType")
    file_name: str | None = Field(alias="fileName")
    content_sha256: str = Field(alias="contentSha256")


class ConfirmedTaskInput(_StrictModel):
    """§4.2 ConfirmedTaskInput：八键必填，startTime/dueTime/sourceExcerpt 可 null。"""

    draft_id: str = Field(alias="draftId")
    title: str
    start_time: TimeInfoInput | None = Field(alias="startTime")
    due_time: TimeInfoInput | None = Field(alias="dueTime")
    requirements: list[str]
    applicability: ApplicabilityInput
    source_excerpt: str | None = Field(alias="sourceExcerpt")
    reminder: ReminderInput


@dataclass
class ConfirmOutcome:
    status_code: int
    body: dict[str, Any] | None = None
    error: ApiError | None = None


# --------------------------------------------------------------------------- #
# canonical digest
# --------------------------------------------------------------------------- #


def _canonicalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalise(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalise(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """递归按键排序、数组保序、无多余空格的规范 JSON。"""
    return json.dumps(
        _canonicalise(value), ensure_ascii=False, separators=(",", ":")
    )


def confirmation_digest(confirmation: dict[str, Any]) -> str:
    """确认请求摘要：规范 JSON 的 UTF-8 SHA-256（§4.1.5）。"""
    return hashlib.sha256(canonical_json(confirmation).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# error helpers
# --------------------------------------------------------------------------- #


def _bad_request(message: str, field: str | None = None) -> ConfirmOutcome:
    errors = (
        [FieldError(field, "invalid_request", message)] if field is not None else []
    )
    return ConfirmOutcome(400, error=ApiError(400, "invalid_request", message, errors))


def _source_input_error(exc: ValidationError) -> ConfirmOutcome:
    """来源确认输入的任何问题都是 400 invalid_request（§4.2）。"""
    field_errors = [
        FieldError(
            field=f"source.{_field_path(tuple(err.get('loc', ())))}".rstrip("."),
            code=str(err.get("type", "invalid")),
            message=str(err.get("msg", "invalid")),
        )
        for err in exc.errors()
    ]
    return ConfirmOutcome(
        400,
        error=ApiError(
            400, "invalid_request", "来源确认字段校验失败。", field_errors
        ),
    )


def _prefix_path(error: ApiError, prefix: str) -> ApiError:
    return ApiError(
        error.status_code,
        error.code,
        error.message,
        [
            FieldError(
                f"{prefix}.{fe.field}" if fe.field else prefix, fe.code, fe.message
            )
            for fe in error.field_errors
        ],
    )


def _replay_or_conflict(existing: dict[str, Any], digest: str) -> ConfirmOutcome:
    if existing.get("requestSha256") == digest:
        return ConfirmOutcome(200, body=deepcopy(existing.get("response") or {}))
    return ConfirmOutcome(
        409,
        error=ApiError(
            409,
            "idempotency_conflict",
            "同一 draftSetId 已用不同内容确认过。",
        ),
    )


def _storage_outcome(error: dict[str, Any]) -> ConfirmOutcome:
    code = str(error.get("code", "storage_read_failed"))
    if code not in (
        "storage_read_failed",
        "storage_write_failed",
        "storage_version_unsupported",
    ):
        code = "storage_read_failed"
    return ConfirmOutcome(500, error=ApiError(500, code, str(error.get("message", ""))))


# --------------------------------------------------------------------------- #
# preparation
# --------------------------------------------------------------------------- #


@dataclass
class _Prepared:
    source: Source
    tasks: list[Task]
    record: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)


def _verify_source_against_cache(
    source_input: SourceConfirmationInput, entry: DraftSetCacheEntry
) -> ConfirmOutcome | None:
    cached = entry.source
    # T11 起图片确认正式支持：不再拦截 kind=image，仅核对元数据一致性
    mismatches = [
        (source_input.id, cached.get("id")),
        (source_input.imported_at, cached.get("importedAt")),
        (source_input.mime_type, cached.get("mimeType")),
        (source_input.content_sha256, cached.get("contentSha256")),
        (source_input.message_date, cached.get("messageDate")),
    ]
    if any(submitted != original for submitted, original in mismatches):
        return ConfirmOutcome(
            409,
            error=ApiError(
                409,
                "source_content_mismatch",
                "确认来源与提取时的来源元数据不一致。",
            ),
        )
    return None


def _validate_source_input(
    source_input: SourceConfirmationInput,
) -> ConfirmOutcome | None:
    """契约 §4.2 的 kind 相关规则：text 时 originalText 非空、fileName=null；
    image 时 originalText=null。文字路径行为与 T06 一致。"""
    if source_input.kind == "text":
        if not source_input.original_text:
            return ConfirmOutcome(
                400,
                error=ApiError(
                    400,
                    "invalid_request",
                    "来源确认字段校验失败。",
                    [FieldError("source.originalText", "invalid", "text 来源必须为非空原文。")],
                ),
            )
        if source_input.file_name is not None:
            return ConfirmOutcome(
                400,
                error=ApiError(
                    400,
                    "invalid_request",
                    "来源确认字段校验失败。",
                    [FieldError("source.fileName", "invalid", "text 来源 fileName 必须为 null。")],
                ),
            )
    else:  # image
        if source_input.original_text is not None:
            return ConfirmOutcome(
                400,
                error=ApiError(
                    400,
                    "invalid_request",
                    "来源确认字段校验失败。",
                    [FieldError("source.originalText", "invalid", "image 来源 originalText 必须为 null。")],
                ),
            )
    return None


def _build_source(
    source_input: SourceConfirmationInput, relative_path: str | None
) -> tuple[Source | None, ConfirmOutcome | None]:
    """构造保存的 Source。图片：relativePath 用落盘路径（D-013）；文字：null。"""
    payload = {
        "id": source_input.id,
        "kind": source_input.kind,
        "originalText": source_input.original_text,
        "relativePath": relative_path if source_input.kind == "image" else None,
        "mimeType": source_input.mime_type,
        "fileName": source_input.file_name,
        "messageDate": source_input.message_date,
        "importedAt": source_input.imported_at,
        "contentSha256": source_input.content_sha256,
    }
    try:
        return Source.model_validate(payload), None
    except ValidationError as exc:
        return None, _source_input_error(exc)


def _check_draft_membership(
    task_inputs: list[ConfirmedTaskInput], entry: DraftSetCacheEntry
) -> ConfirmOutcome | None:
    cached_ids = [draft["id"] for draft in entry.drafts]
    seen: set[str] = set()
    for index, task in enumerate(task_inputs):
        field_path = f"confirmedTasks[{index}].draftId"
        if task.draft_id not in cached_ids:
            return ConfirmOutcome(
                422,
                error=ApiError(
                    422,
                    "task_validation_failed",
                    "任务字段校验失败。",
                    [FieldError(field_path, "not_in_batch", "该 draftId 不属于本批次。")],
                ),
            )
        if task.draft_id in seen:
            return ConfirmOutcome(
                422,
                error=ApiError(
                    422,
                    "task_validation_failed",
                    "任务字段校验失败。",
                    [FieldError(field_path, "duplicate", "同一 draftId 在批内重复。")],
                ),
            )
        seen.add(task.draft_id)
    return None


def _build_tasks(
    task_inputs: list[ConfirmedTaskInput],
    source_id: str,
    now: datetime,
) -> tuple[list[Task] | None, ConfirmOutcome | None]:
    timestamp = now.isoformat()
    tasks: list[Task] = []
    for index, task_input in enumerate(task_inputs):
        prefix = f"confirmedTasks[{index}]"
        payload: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "draftId": task_input.draft_id,
            "sourceId": source_id,
            "title": task_input.title,
            "startTime": (
                None
                if task_input.start_time is None
                else _time_info_payload(task_input.start_time)
            ),
            "dueTime": (
                None
                if task_input.due_time is None
                else _time_info_payload(task_input.due_time)
            ),
            "requirements": list(task_input.requirements),
            "applicability": {
                "text": task_input.applicability.text,
                "status": task_input.applicability.status,
            },
            "sourceExcerpt": task_input.source_excerpt,
            "reviewIssues": [],
            "status": "open",
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }

        # 生成提醒（§3.5）；确认写入必须显式带 draftSetId（D-015）
        candidate = _reminder_candidate(task_input.reminder, str(uuid.uuid4()))
        if candidate["mode"] == "manual" and candidate["requestedAt"] is not None:
            try:
                requested = datetime.fromisoformat(str(candidate["requestedAt"]))
            except ValueError:
                requested = None
            if requested is not None and requested < now:
                return None, ConfirmOutcome(
                    422,
                    error=ApiError(
                        422,
                        "reminder_time_in_past",
                        "提醒时刻已经过去。",
                        [
                            FieldError(
                                f"{prefix}.reminder.requestedAt",
                                "in_past",
                                "提醒时刻已经过去。",
                            )
                        ],
                    ),
                )
        failure = _resolve_reminder(candidate, payload, "open")
        if failure is not None:
            return None, ConfirmOutcome(
                failure.status_code, error=_prefix_path(failure, prefix)
            )
        payload["reminder"] = candidate

        try:
            tasks.append(Task.model_validate(payload))
        except ValidationError as exc:
            error = _validation_error_to_api_error(exc, prefix=prefix)
            return None, ConfirmOutcome(error.status_code, error=error)
    return tasks, None


def _prepare(
    entry: DraftSetCacheEntry,
    source_input: SourceConfirmationInput,
    task_inputs: list[ConfirmedTaskInput],
    digest: str,
    draft_set_id: str,
    now: datetime,
) -> tuple[_Prepared | None, ConfirmOutcome | None]:
    mismatch = _verify_source_against_cache(source_input, entry)
    if mismatch is not None:
        return None, mismatch

    kind_failure = _validate_source_input(source_input)
    if kind_failure is not None:
        return None, kind_failure

    # 图片：沿用提取时落盘的相对路径（缓存条目持有的 source 九键）
    cached_relative = entry.source.get("relativePath") if entry.source else None
    source, failure = _build_source(source_input, cached_relative)
    if failure is not None:
        return None, failure
    assert source is not None

    membership = _check_draft_membership(task_inputs, entry)
    if membership is not None:
        return None, membership

    tasks, failure = _build_tasks(task_inputs, source.id, now)
    if failure is not None:
        return None, failure
    assert tasks is not None

    response = {
        "source": to_source_metadata(source).model_dump(mode="json", by_alias=True),
        "tasks": [task.model_dump(mode="json", by_alias=True) for task in tasks],
        "savedAt": now.isoformat(),
    }
    record = {
        "draftSetId": draft_set_id,   # D-015：显式传入，禁止自动生成
        "requestSha256": digest,
        "response": response,
    }
    return _Prepared(source=source, tasks=tasks, record=record, response=response), None


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def confirm_draft_set(
    *,
    root: Path,
    cache: DraftSetCache,
    draft_set_id: str,
    confirmation: dict[str, Any],
    now: datetime,
    source_bytes: bytes | None = None,
) -> ConfirmOutcome:
    """Validate and atomically save one confirmation batch (§2.1 / §4.1).

    source_bytes：图片来源的原始字节（T11）。提供时按字节核对 contentSha256；
    不提供（文字路径）沿用 originalText 的哈希——文字路径行为不变。
    """
    # --- 根形状 ---
    if not isinstance(confirmation, dict):
        return _bad_request("确认请求必须是 JSON 对象。")
    unknown = [key for key in confirmation if key not in CONFIRM_ROOT_KEYS]
    if unknown:
        return ConfirmOutcome(
            400,
            error=ApiError(
                400,
                "invalid_request",
                "包含不可写或未知字段。",
                [FieldError(key, "unknown_field", "该字段不可写或不存在。") for key in unknown],
            ),
        )
    if "source" not in confirmation or "confirmedTasks" not in confirmation:
        missing = [k for k in CONFIRM_ROOT_KEYS if k not in confirmation]
        return ConfirmOutcome(
            400,
            error=ApiError(
                400,
                "invalid_request",
                "确认请求必须同时包含 source 与 confirmedTasks。",
                [FieldError(key, "missing", "缺少必填键。") for key in missing],
            ),
        )
    source_raw = confirmation["source"]
    tasks_raw = confirmation["confirmedTasks"]
    if not isinstance(source_raw, dict):
        return _bad_request("source 必须是 JSON 对象。", "source")
    if not isinstance(tasks_raw, list):
        return _bad_request("confirmedTasks 必须是数组。", "confirmedTasks")
    if not tasks_raw:
        return ConfirmOutcome(
            422,
            error=ApiError(422, "empty_confirmation", "确认任务列表为空。"),
        )

    # --- DTO 校验 ---
    try:
        source_input = SourceConfirmationInput.model_validate(source_raw)
    except ValidationError as exc:
        return _source_input_error(exc)

    task_inputs: list[ConfirmedTaskInput] = []
    for index, item in enumerate(tasks_raw):
        if not isinstance(item, dict):
            return ConfirmOutcome(
                422,
                error=ApiError(
                    422,
                    "task_validation_failed",
                    "任务字段校验失败。",
                    [
                        FieldError(
                            f"confirmedTasks[{index}]",
                            "not_an_object",
                            "任务项必须是 JSON 对象。",
                        )
                    ],
                ),
            )
        try:
            task_inputs.append(ConfirmedTaskInput.model_validate(item))
        except ValidationError as exc:
            error = _validation_error_to_api_error(
                exc, prefix=f"confirmedTasks[{index}]"
            )
            return ConfirmOutcome(error.status_code, error=error)

    # --- 摘要与重传字节核对（先于记录查询，§2.1） ---
    digest = confirmation_digest(
        {"source": source_raw, "confirmedTasks": tasks_raw}
    )
    if source_bytes is not None:
        # 图片：按原始字节核对
        recomputed = hashlib.sha256(source_bytes).hexdigest()
    elif source_input.original_text is not None:
        # 文字：沿用 originalText 的哈希（行为不变）
        recomputed = hashlib.sha256(source_input.original_text.encode("utf-8")).hexdigest()
    else:
        # 图片源但未随请求提供字节：无法核对 → 按不一致处理，避免接受未核对来源
        recomputed = None
    if recomputed != source_input.content_sha256:
        return ConfirmOutcome(
            409,
            error=ApiError(
                409,
                "source_content_mismatch",
                "重传来源内容与 contentSha256 不符。",
            ),
        )

    # --- 预检：已有确认记录 / 进程内草稿缓存 ---
    loaded = load_snapshot(root)
    if loaded.error is not None:
        return _storage_outcome(loaded.error)
    assert loaded.snapshot is not None

    existing = loaded.snapshot.confirmed_draft_sets.get(draft_set_id)
    if existing is not None:
        return _replay_or_conflict(existing, digest)

    entry = cache.get(draft_set_id)
    if entry is None:
        return ConfirmOutcome(
            404,
            error=ApiError(
                404, "draft_set_not_found", "草稿集不存在或已因重启失效。"
            ),
        )

    prepared, failure = _prepare(
        entry, source_input, task_inputs, digest, draft_set_id, now
    )
    if failure is not None:
        return failure
    assert prepared is not None

    # --- 锁内提交 ---
    outcome: dict[str, Any] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        current = snapshot.confirmed_draft_sets.get(draft_set_id)
        if current is not None:
            # 并发到达的同一批次：按最新持久记录回放或报冲突
            outcome["record"] = current
            return snapshot
        updated = snapshot.add_source(prepared.source)
        for task in prepared.tasks:
            updated = updated.add_task(task)
        return updated.add_confirmation(prepared.record)

    result = commit(root, _mutate)
    if result.error is not None:
        return _storage_outcome(result.error)
    # 项④：提交成功后记录 warning（如 backup_not_refreshed），不改变成功语义
    note_commit_warning("confirm draft set", result)

    if "record" in outcome:
        return _replay_or_conflict(outcome["record"], digest)

    return ConfirmOutcome(200, body=deepcopy(prepared.response))
