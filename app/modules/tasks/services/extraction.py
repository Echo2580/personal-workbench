"""Extraction service: turn a model result into a validated DraftSet (T07)."""

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.modules.tasks.domain import DraftSet, Source, TaskDraft
from app.modules.tasks.services.model_adapter import ExtractionModel, ImageExtractionModel


DRAFT_NONE_REMINDER: dict[str, Any] = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": None,
}

# 模型不得自行决定的只读字段：服务端一律覆盖（D-013/D-015）
_SERVER_OWNED_DRAFT_KEYS = ("id", "sourceId", "reviewIssues", "reminder")


class DraftValidationError(Exception):
    """模型输出可解析但草稿字段非法 → 502 draft_validation_failed。"""

    def __init__(self, validation_error: ValidationError | None, index: int, message: str = ""):
        self.validation_error = validation_error
        self.index = index
        self.message = message or f"draft {index} failed validation"
        super().__init__(self.message)


@dataclass
class DraftSetCacheEntry:
    """进程内草稿集缓存条目；确认成功后仍保留（幂等靠持久记录）。"""

    draft_set_id: str
    source: dict[str, Any]        # 完整九键 Source（含 originalText）
    drafts: list[dict[str, Any]]  # 已校验的 TaskDraft JSON（camelCase）
    created_at: str


@dataclass
class DraftSetCache:
    """按 draftSetId 索引的进程内缓存（随 app 实例生命周期）。"""

    _entries: dict[str, DraftSetCacheEntry] = field(default_factory=dict)

    def put(self, entry: DraftSetCacheEntry) -> None:
        self._entries[entry.draft_set_id] = entry

    def get(self, draft_set_id: str) -> DraftSetCacheEntry | None:
        return self._entries.get(draft_set_id)

    def __contains__(self, draft_set_id: object) -> bool:
        return draft_set_id in self._entries

    def __len__(self) -> int:
        return len(self._entries)


def _normalise_draft(
    raw: Any, *, draft_id: str, source_id: str
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DraftValidationError(None, 0, "draft must be a JSON object")

    payload = {key: value for key, value in raw.items() if key not in _SERVER_OWNED_DRAFT_KEYS}
    for key in ("startTime", "dueTime"):
        info = payload.get(key)
        if isinstance(info, dict):
            info = dict(info)
            # 服务端固定时区，不接受模型提供的值
            info["timeZone"] = "Asia/Shanghai"
            payload[key] = info
    payload["id"] = draft_id
    payload["sourceId"] = source_id
    payload["reviewIssues"] = []           # 由 TaskDraft 按最终字段重算
    payload["reminder"] = deepcopy(DRAFT_NONE_REMINDER)
    return payload


def _validate_raw_drafts(
    raw_drafts: list[Any], source_id: str
) -> list[TaskDraft]:
    """把模型返回的草稿逐条规范并校验；任何一条不合法整体报错（不部分接受）。"""
    validated: list[TaskDraft] = []
    for index, raw in enumerate(raw_drafts):
        try:
            payload = _normalise_draft(raw, draft_id=str(uuid.uuid4()), source_id=source_id)
        except DraftValidationError as exc:
            raise DraftValidationError(None, index, exc.message) from exc
        try:
            validated.append(TaskDraft.model_validate(payload))
        except ValidationError as exc:
            raise DraftValidationError(exc, index) from exc
    return validated


def _build_draft_set(
    draft_set_id: str, source: Source, validated: list[TaskDraft]
) -> DraftSet:
    draft_payloads = [
        draft.model_dump(mode="json", by_alias=True) for draft in validated
    ]
    return DraftSet.model_validate(
        {
            "draftSetId": draft_set_id,
            "source": {
                "id": source.id,
                "kind": source.kind,
                "mimeType": source.mime_type,
                "fileName": source.file_name,
                "messageDate": source.message_date,
                "importedAt": source.imported_at,
                "contentSha256": source.content_sha256,
            },
            "status": "review" if validated else "no_tasks",
            "drafts": draft_payloads,
        }
    )


def _build_entry(
    draft_set_id: str,
    source: Source,
    validated: list[TaskDraft],
    imported_at: str,
) -> DraftSetCacheEntry:
    return DraftSetCacheEntry(
        draft_set_id=draft_set_id,
        source=source.model_dump(mode="json", by_alias=True),
        drafts=[
            deepcopy(draft.model_dump(mode="json", by_alias=True))
            for draft in validated
        ],
        created_at=imported_at,
    )


def run_extraction(
    model: ExtractionModel,
    original_text: str,
    message_date: str | None,
    now: datetime,
) -> tuple[DraftSet, DraftSetCacheEntry]:
    """Call the model and build a validated DraftSet plus its cache entry.

    Model-level failures propagate as the adapter's exceptions; invalid draft
    content raises DraftValidationError.
    """
    source_id = str(uuid.uuid4())
    draft_set_id = str(uuid.uuid4())
    imported_at = now.isoformat()
    content_sha256 = hashlib.sha256(original_text.encode("utf-8")).hexdigest()

    result = model.extract_drafts(original_text, message_date)

    validated = _validate_raw_drafts(result.drafts, source_id)

    source = Source.model_validate(
        {
            "id": source_id,
            "kind": "text",
            "originalText": original_text,
            "relativePath": None,
            "mimeType": "text/plain; charset=utf-8",
            "fileName": None,
            "messageDate": message_date,
            "importedAt": imported_at,
            "contentSha256": content_sha256,
        }
    )

    return (
        _build_draft_set(draft_set_id, source, validated),
        _build_entry(draft_set_id, source, validated, imported_at),
    )


def run_image_extraction(
    model: ImageExtractionModel,
    *,
    image_bytes: bytes,
    content_type: str,
    message_date: str | None,
    now: datetime,
    source_id: str,
    relative_path: str,
    content_sha256: str,
    file_name: str | None = None,
) -> tuple[DraftSet, DraftSetCacheEntry]:
    """图片提取（T12）：调用视觉模型 → 校验草稿 → DraftSet + 缓存条目。

    source_id/relative_path/content_sha256 来自 T11 的落盘结果（同一来源身份贯穿
    提取与确认）；本函数不写任何文件，也不落 JSON 快照。
    """
    draft_set_id = str(uuid.uuid4())
    imported_at = now.isoformat()

    result = model.extract_drafts_from_image(image_bytes, content_type, message_date)

    validated = _validate_raw_drafts(result.drafts, source_id)

    source = Source.model_validate(
        {
            "id": source_id,
            "kind": "image",
            "originalText": None,
            "relativePath": relative_path,
            "mimeType": content_type,
            "fileName": file_name,
            "messageDate": message_date,
            "importedAt": imported_at,
            "contentSha256": content_sha256,
        }
    )

    return (
        _build_draft_set(draft_set_id, source, validated),
        _build_entry(draft_set_id, source, validated, imported_at),
    )
