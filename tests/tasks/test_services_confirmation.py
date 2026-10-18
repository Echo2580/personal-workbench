"""构造样本测试 T07 确认保存服务层（幂等三分支、全有或全无、重启语义）。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.tasks.services.confirmation import (
    canonical_json,
    confirm_draft_set,
    confirmation_digest,
)
from app.modules.tasks.services.extraction import DraftSetCache, run_extraction
from app.modules.tasks.services.model_adapter import MockExtractionModel
from app.modules.tasks.storage import load_snapshot


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=SHANGHAI)
TEXT = "请于10月20日10:00前交报告，需打印纸质版。"

DRAFT_DATED = {
    "title": "交报告",
    "startTime": None,
    "dueTime": {
        "rawExpression": "10月20日10:00",
        "precision": "datetime",
        "resolvedValue": "2026-10-20T10:00:00+08:00",
        "status": "resolved",
    },
    "requirements": ["打印纸质版"],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "请于10月20日10:00前交报告",
}

DRAFT_CONDITIONAL = {
    "title": "交周报",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": "仅限本班同学", "status": "needs_confirmation"},
    "sourceExcerpt": "另需交周报",
}


# ---------------------------------------------------------------- helpers

def build(drafts, *, text: str = TEXT, message_date: str | None = None):
    """跑一次提取并放入缓存，返回 (draft_set, entry, cache)。"""
    model = MockExtractionModel(drafts=deepcopy(drafts))
    draft_set, entry = run_extraction(model, text, message_date, NOW)
    cache = DraftSetCache()
    cache.put(entry)
    return draft_set, entry, cache


def to_input_time(info):
    if info is None:
        return None
    return {
        key: info[key]
        for key in ("rawExpression", "precision", "resolvedValue", "status")
    }


def source_input(entry, *, text: str = TEXT, **overrides):
    src = entry.source
    payload = {
        "id": src["id"],
        "kind": "text",
        "originalText": text,
        "messageDate": src["messageDate"],
        "importedAt": src["importedAt"],
        "mimeType": src["mimeType"],
        "fileName": src["fileName"],
        "contentSha256": src["contentSha256"],
    }
    payload.update(overrides)
    return payload


def task_input(draft, **overrides):
    payload = {
        "draftId": draft["id"],
        "title": draft["title"],
        "startTime": to_input_time(draft["startTime"]),
        "dueTime": to_input_time(draft["dueTime"]),
        "requirements": list(draft["requirements"]),
        "applicability": dict(draft["applicability"]),
        "sourceExcerpt": draft["sourceExcerpt"],
        "reminder": {
            "mode": "none",
            "requestedAt": None,
            "relativeTo": None,
            "offsetMinutes": None,
        },
    }
    payload.update(overrides)
    return payload


def confirmation(entry, drafts, *, text: str = TEXT, **source_overrides):
    return {
        "source": source_input(entry, text=text, **source_overrides),
        "confirmedTasks": [task_input(d) for d in drafts],
    }


# ---------------------------------------------------------------- 摘要规范化

def test_canonical_json_sorts_keys_and_preserves_array_order():
    assert canonical_json({"b": 1, "a": {"d": 2, "c": 3}}) == '{"a":{"c":3,"d":2},"b":1}'
    # 数组顺序不变
    assert canonical_json({"x": [3, 1, 2]}) == '{"x":[3,1,2]}'
    # 无多余空格
    assert " " not in canonical_json({"a": [1, 2], "b": None})
    # null 保留
    assert canonical_json({"a": None}) == '{"a":null}'


def test_confirmation_digest_is_stable_across_key_order():
    body = {
        "source": {"id": "a", "contentSha256": "c" * 64},
        "confirmedTasks": [{"draftId": "d", "title": "t"}],
    }
    reordered = {
        "confirmedTasks": [{"title": "t", "draftId": "d"}],
        "source": {"contentSha256": "c" * 64, "id": "a"},
    }

    assert confirmation_digest(body) == confirmation_digest(reordered)
    assert len(confirmation_digest(body)) == 64

    # 数组顺序不同 → 摘要不同
    two = {
        "source": body["source"],
        "confirmedTasks": [{"draftId": "d", "title": "t"}, {"draftId": "e", "title": "u"}],
    }
    swapped = {
        "source": body["source"],
        "confirmedTasks": list(reversed(two["confirmedTasks"])),
    }
    assert confirmation_digest(two) != confirmation_digest(swapped)


# ---------------------------------------------------------------- 成功路径

def test_confirm_success_persists_source_tasks_and_record(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED, DRAFT_CONDITIONAL])
    drafts = entry.drafts
    body = confirmation(entry, drafts)

    outcome = confirm_draft_set(
        root=tmp_path,
        cache=cache,
        draft_set_id=entry.draft_set_id,
        confirmation=body,
        now=NOW,
    )

    assert outcome.error is None
    assert outcome.status_code == 200
    response = outcome.body
    assert set(response) == {"source", "tasks", "savedAt"}
    assert response["savedAt"] == NOW.isoformat()
    # 来源响应是七键元数据
    assert set(response["source"]) == {
        "id",
        "kind",
        "mimeType",
        "fileName",
        "messageDate",
        "importedAt",
        "contentSha256",
    }
    assert len(response["tasks"]) == 2
    for task in response["tasks"]:
        assert task["status"] == "open"
        assert task["sourceId"] == entry.source["id"]
        assert task["createdAt"] == NOW.isoformat()
        assert task["updatedAt"] == NOW.isoformat()
        assert task["reminder"]["revision"] is not None
        assert task["id"] not in {d["id"] for d in drafts}
    assert response["tasks"][0]["draftId"] == drafts[0]["id"]

    # 落盘三分区一致
    snapshot = load_snapshot(tmp_path).snapshot
    assert set(snapshot.sources) == {entry.source["id"]}
    assert set(snapshot.tasks) == {t["id"] for t in response["tasks"]}
    assert set(snapshot.confirmed_draft_sets) == {entry.draft_set_id}
    record = snapshot.confirmed_draft_sets[entry.draft_set_id]
    # 值恰为契约两键
    assert set(record) == {"requestSha256", "response"}
    assert record["requestSha256"] == confirmation_digest(body)
    assert record["response"] == response

    payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert set(payload["confirmedDraftSets"][entry.draft_set_id]) == {
        "requestSha256",
        "response",
    }
    # 原文只落内部来源，不进确认记录
    assert entry.source["originalText"] not in json.dumps(
        payload["confirmedDraftSets"], ensure_ascii=False
    )


def test_confirm_source_written_at_most_once(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    assert confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    ).error is None

    payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert list(payload["sources"]) == [entry.source["id"]]


# ---------------------------------------------------------------- 幂等三分支

def test_confirm_replay_same_digest_returns_original_response(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    first = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )
    # 第二次用更晚的时间——回放必须返回首次的 savedAt，不重新生成
    later = datetime(2026, 10, 16, 18, 0, 0, tzinfo=SHANGHAI)
    replay = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=deepcopy(body), now=later,
    )

    assert replay.error is None
    assert replay.status_code == 200
    assert replay.body == first.body
    snapshot = load_snapshot(tmp_path).snapshot
    assert len(snapshot.tasks) == 1


def test_confirm_conflict_on_different_digest(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    assert confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    ).error is None

    changed = deepcopy(body)
    changed["confirmedTasks"][0]["title"] = "改过的标题"
    conflict = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=changed, now=NOW,
    )

    assert conflict.error is not None
    assert conflict.error.status_code == 409
    assert conflict.error.code == "idempotency_conflict"
    # 不覆盖首次结果
    snapshot = load_snapshot(tmp_path).snapshot
    assert len(snapshot.tasks) == 1
    assert snapshot.tasks[list(snapshot.tasks)[0]].title == "交报告"


def test_confirm_unknown_draft_set_returns_404(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)

    outcome = confirm_draft_set(
        root=tmp_path,
        cache=DraftSetCache(),  # 空缓存 = 重启后的进程
        draft_set_id=entry.draft_set_id,
        confirmation=body,
        now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 404
    assert outcome.error.code == "draft_set_not_found"
    # 未产生任何落盘
    assert not (tmp_path / "state.json").exists()


def test_confirm_content_sha_mismatch_returns_409(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    # 原文被改动但摘要沿用旧值
    body["source"]["originalText"] = TEXT + "（被篡改）"

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 409
    assert outcome.error.code == "source_content_mismatch"
    assert not (tmp_path / "state.json").exists()


def test_confirm_source_metadata_mismatch_returns_409(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    body["source"]["importedAt"] = "2026-10-16T13:00:00+08:00"

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 409
    assert outcome.error.code == "source_content_mismatch"


def test_confirm_content_sha_checked_before_record_lookup(tmp_path: Path):
    """即使 draftSetId 已有记录，摘要不符也先报 content 冲突（§2.1 顺序）。"""
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    first = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )
    assert first.error is None

    tampered = deepcopy(body)
    tampered["source"]["originalText"] = "完全不同的原文"
    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=tampered, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 409
    assert outcome.error.code == "source_content_mismatch"


# ---------------------------------------------------------------- 批内校验

def test_confirm_rejects_draft_id_outside_batch(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED, DRAFT_CONDITIONAL])
    body = confirmation(entry, entry.drafts)
    body["confirmedTasks"][0]["draftId"] = "99999999-9999-4999-8999-999999999999"

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 422
    assert outcome.error.code == "task_validation_failed"
    assert any(
        "draftId" in fe.field for fe in outcome.error.field_errors
    ), [fe.field for fe in outcome.error.field_errors]
    assert not (tmp_path / "state.json").exists()


def test_confirm_rejects_duplicate_draft_id_in_batch(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    body["confirmedTasks"] = [task_input(entry.drafts[0]), task_input(entry.drafts[0])]

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 422
    assert not (tmp_path / "state.json").exists()


def test_confirm_batch_is_all_or_nothing(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED, DRAFT_CONDITIONAL])
    body = confirmation(entry, entry.drafts)
    # 第二个任务非法（日期精度但无解析值）
    body["confirmedTasks"][1]["dueTime"] = {
        "rawExpression": "周五前",
        "precision": "relative",
        "resolvedValue": None,
        "status": "resolved",
    }

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 422
    assert any(
        fe.field.startswith("confirmedTasks[1]") for fe in outcome.error.field_errors
    ), [fe.field for fe in outcome.error.field_errors]
    # 零写入：第一个合法任务也不落盘
    assert not (tmp_path / "state.json").exists()


def test_confirm_empty_task_array_is_rejected(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    body["confirmedTasks"] = []

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 422
    assert outcome.error.code == "empty_confirmation"
    assert not (tmp_path / "state.json").exists()


def test_confirm_manual_reminder_in_the_past_is_rejected(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    body["confirmedTasks"][0]["reminder"] = {
        "mode": "manual",
        "requestedAt": "2020-01-01T00:00:00+08:00",
        "relativeTo": None,
        "offsetMinutes": None,
    }

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is not None
    assert outcome.error.status_code == 422
    assert outcome.error.code == "reminder_time_in_past"


def test_confirm_relative_reminder_is_scheduled_on_open_task(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    body["confirmedTasks"][0]["reminder"] = {
        "mode": "relative",
        "requestedAt": None,
        "relativeTo": "due",
        "offsetMinutes": 30,
    }

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is None
    reminder = outcome.body["tasks"][0]["reminder"]
    assert reminder["state"] == "scheduled"
    assert reminder["scheduledAt"] == "2026-10-20T09:30:00+08:00"
    assert reminder["revision"] is not None
    assert reminder["acknowledgedAt"] is None


def test_confirm_recomputes_review_issues(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_CONDITIONAL])
    body = confirmation(entry, entry.drafts)

    outcome = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )

    assert outcome.error is None
    codes = [i["code"] for i in outcome.body["tasks"][0]["reviewIssues"]]
    assert codes == ["applicability_needs_confirmation"]


# ---------------------------------------------------------------- 无写入保证

def test_rejected_and_replayed_requests_perform_no_disk_write(
    tmp_path: Path, monkeypatch
):
    """拒绝分支与回放分支都不得触碰磁盘（注入写失败后仍应得到原错误/原结果）。"""
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    assert confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    ).error is None
    baseline = (tmp_path / "state.json").read_bytes()

    import app.modules.tasks.storage.state_store as state_store

    def _boom(*args, **kwargs):
        raise OSError("磁盘写入被注入失败")

    monkeypatch.setattr(state_store.os, "replace", _boom)

    replay = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=deepcopy(body), now=NOW,
    )
    assert replay.error is None and replay.status_code == 200

    missing = confirm_draft_set(
        root=tmp_path, cache=DraftSetCache(),
        draft_set_id="00000000-0000-4000-8000-000000000000",
        confirmation=body, now=NOW,
    )
    assert missing.error is not None and missing.error.status_code == 404

    assert (tmp_path / "state.json").read_bytes() == baseline


# ---------------------------------------------------------------- 重启语义

def test_restart_replays_from_record_but_cache_miss_is_404(tmp_path: Path):
    draft_set, entry, cache = build([DRAFT_DATED])
    body = confirmation(entry, entry.drafts)
    first = confirm_draft_set(
        root=tmp_path, cache=cache, draft_set_id=entry.draft_set_id,
        confirmation=body, now=NOW,
    )
    assert first.error is None

    # 模拟重启：新的空缓存，同一持久根
    restarted_cache = DraftSetCache()

    replay = confirm_draft_set(
        root=tmp_path, cache=restarted_cache, draft_set_id=entry.draft_set_id,
        confirmation=deepcopy(body), now=NOW,
    )
    assert replay.error is None
    assert replay.body == first.body

    # 未确认过的 draftSetId 在重启后 404
    other = build([DRAFT_CONDITIONAL])
    assert other[1].draft_set_id != entry.draft_set_id
    miss = confirm_draft_set(
        root=tmp_path,
        cache=restarted_cache,
        draft_set_id=other[1].draft_set_id,
        confirmation=confirmation(other[1], other[1].drafts),
        now=NOW,
    )
    assert miss.error is not None
    assert miss.error.status_code == 404
