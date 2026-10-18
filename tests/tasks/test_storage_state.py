"""构造样本测试 T05 存储组件：原子、损坏、锁与实体校验。

所有数据均为实体/存储测试的构造样本，不代表真实提醒或业务数据。
"""

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.modules.tasks.domain import Source, SourceMetadata, Task, TaskFields, TaskDraft
from app.modules.tasks.storage.state_store import (
    SCHEMA_VERSION,
    CommitResult,
    LoadResult,
    Snapshot,
    commit,
    load_snapshot,
    snapshot_errors,
)


SOURCE_ID_A = "11111111-1111-4111-8111-111111111111"
SOURCE_ID_B = "22222222-2222-4222-8222-222222222222"
DRAFT_ID = "33333333-3333-4333-8333-333333333333"
SET_ID = "44444444-4444-4444-8444-444444444444"
VERSION = "55555555-5555-4555-8555-555555555555"
STAMP = "2026-10-20T08:00:00+08:00"

TEXT_META_A: dict[str, Any] = {
    "id": SOURCE_ID_A,
    "kind": "text",
    "originalText": "  请交报告\n",
    "relativePath": None,
    "mimeType": "text/plain; charset=utf-8",
    "fileName": None,
    "messageDate": None,
    "importedAt": STAMP,
    "contentSha256": "a" * 64,
}

TEXT_META_B: dict[str, Any] = {
    "id": SOURCE_ID_B,
    "kind": "text",
    "originalText": "  请提交周报\n",
    "relativePath": None,
    "mimeType": "text/plain; charset=utf-8",
    "fileName": None,
    "messageDate": None,
    "importedAt": STAMP,
    "contentSha256": "b" * 64,
}

NONE_REMINDER: dict[str, Any] = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": None,
}


def _saved_task(index: int, *, source_id: str = SOURCE_ID_A) -> dict[str, Any]:
    return {
        "id": f"33333333-3333-4333-8333-{index:012d}",
        "draftId": DRAFT_ID,
        "sourceId": source_id,
        "title": f"事项 {index}",
        "startTime": None,
        "dueTime": None,
        "requirements": [f"要求 {index}"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": f"原文片段 {index}",
        "reviewIssues": [],
        "status": "open",
        "reminder": {**NONE_REMINDER, "revision": VERSION},
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }


def _confirmation(draft_set_id: str, response_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "draftSetId": draft_set_id,
        "requestSha256": "f" * 64,
        "response": response_payload,
    }


def _write_raw(root: Path, raw: str) -> None:
    (root / "state.json").write_text(raw, encoding="utf-8")


def _read_raw(root: Path) -> str:
    return (root / "state.json").read_text(encoding="utf-8")


def _main_present(root: Path) -> bool:
    return (root / "state.json").exists()


def _bak_present(root: Path) -> bool:
    return (root / "state.json.bak").exists()


def test_empty_root_returns_empty_snapshot(tmp_path: Path):
    result = load_snapshot(tmp_path)

    assert result.error is None
    assert result.snapshot is not None
    assert result.snapshot.schema_version == SCHEMA_VERSION
    assert result.snapshot.sources == {}
    assert result.snapshot.tasks == {}
    assert result.snapshot.goals == {}
    assert result.snapshot.confirmed_draft_sets == {}
    assert not _main_present(tmp_path)


def test_first_commit_writes_main_no_backup(tmp_path: Path):
    task = _saved_task(1)
    result = commit(tmp_path, lambda snap: snap.add_task(task))

    assert result.error is None
    assert _main_present(tmp_path)
    assert not _bak_present(tmp_path)
    assert task["id"] in result.snapshot.tasks
    payload = json.loads(_read_raw(tmp_path))
    assert payload["schemaVersion"] == SCHEMA_VERSION
    assert task["id"] in payload["tasks"]


def test_backup_captures_previous_main(tmp_path: Path):
    first = _saved_task(1)
    second = _saved_task(2)
    third = _saved_task(3)

    commit(tmp_path, lambda snap: snap.add_task(first))
    commit(tmp_path, lambda snap: snap.add_task(second))
    payload_before_third = _read_raw(tmp_path)

    commit(tmp_path, lambda snap: snap.add_task(third))

    assert _bak_present(tmp_path)
    bak = json.loads((tmp_path / "state.json.bak").read_text(encoding="utf-8"))
    main = json.loads(_read_raw(tmp_path))
    # .bak holds the snapshot that was main before the latest successful replace.
    assert bak["tasks"] == json.loads(payload_before_third)["tasks"]
    assert third["id"] in main["tasks"]
    assert first["id"] in main["tasks"]
    assert second["id"] in main["tasks"]


def test_atomic_replace_failure_preserves_state(tmp_path: Path, monkeypatch):
    baseline = _saved_task(1)
    initial = commit(tmp_path, lambda snap: snap.add_task(baseline))
    assert initial.error is None

    baseline_payload = _read_raw(tmp_path)
    # First commit: no .bak yet.
    assert not _bak_present(tmp_path)

    # Precise injection: fail only state.json.tmp → state.json. Because the
    # backup replace now happens *after* the main replace, .bak stays
    # byte-unchanged (here: still absent).
    import app.modules.tasks.storage.state_store as state_store_module

    replace_calls: list[tuple[str, str]] = []
    real_replace = state_store_module.os.replace

    def _maybe_boom(src, dst, *args, **kwargs):  # pragma: no cover - injected
        replace_calls.append((str(src), str(dst)))
        if str(src).endswith("state.json.tmp") and str(dst).endswith(
            "state.json"
        ):
            raise OSError("simulated replace failure")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(state_store_module.os, "replace", _maybe_boom)

    new_task = _saved_task(2)
    result = commit(tmp_path, lambda snap: snap.add_task(new_task))

    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"
    assert result.warning is None
    # main untouched, .bak still absent (never created by a failed commit)
    assert _read_raw(tmp_path) == baseline_payload
    assert not _bak_present(tmp_path)
    # no tmp leftovers
    assert not (tmp_path / "state.json.tmp").exists()
    assert not (tmp_path / "state.json.bak.tmp").exists()
    # reload shows baseline only
    reload = load_snapshot(tmp_path)
    assert reload.error is None
    assert set(reload.snapshot.tasks) == {baseline["id"]}


def test_corrupt_json_does_not_overwrite(tmp_path: Path):
    corrupt = '{"schemaVersion":1,"sources":{'
    _write_raw(tmp_path, corrupt)
    pre = _read_raw(tmp_path)

    result = load_snapshot(tmp_path)

    assert result.error is not None
    assert result.error["code"] == "storage_read_failed"
    assert _read_raw(tmp_path) == pre
    # commit after a read failure must not rebuild from scratch
    subsequent = commit(tmp_path, lambda snap: snap)
    assert subsequent.error is not None
    assert subsequent.error["code"] == "storage_read_failed"
    assert _read_raw(tmp_path) == pre


def test_unknown_schema_version_does_not_overwrite(tmp_path: Path):
    payload = json.dumps({"schemaVersion": 4, "sources": {}, "tasks": {}, "confirmedDraftSets": {}})
    _write_raw(tmp_path, payload)
    pre = _read_raw(tmp_path)

    result = load_snapshot(tmp_path)

    assert result.error is not None
    assert result.error["code"] == "storage_version_unsupported"
    assert _read_raw(tmp_path) == pre


def test_invalid_root_structure_does_not_overwrite(tmp_path: Path):
    payload = json.dumps({"schemaVersion": 1, "sources": "not-a-dict"})
    _write_raw(tmp_path, payload)
    pre = _read_raw(tmp_path)

    result = load_snapshot(tmp_path)

    assert result.error is not None
    assert result.error["code"] == "storage_read_failed"
    assert _read_raw(tmp_path) == pre


def test_key_id_mismatch_is_rejected(tmp_path: Path):
    payload = {
        "schemaVersion": 1,
        "sources": {},
        "tasks": {
            "99999999-9999-4999-8999-999999999999": {
                **_saved_task(1),
                "id": "88888888-8888-4888-8888-888888888888",
            }
        },
        "confirmedDraftSets": {},
    }
    _write_raw(tmp_path, json.dumps(payload))

    result = load_snapshot(tmp_path)

    assert result.error is not None
    assert result.error["code"] == "storage_read_failed"
    # file untouched
    assert json.loads(_read_raw(tmp_path)) == payload


def test_entity_validation_rejects_invalid_task(tmp_path: Path):
    bad = _saved_task(1)
    bad["title"] = None  # invalid null for required field

    result = commit(tmp_path, lambda snap: snap.add_task(bad))

    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"
    # nothing landed on disk
    assert not _main_present(tmp_path)
    assert not _bak_present(tmp_path)


def test_entity_validation_rejects_invalid_source_in_mutate(tmp_path: Path):
    # Start clean
    seed = commit(tmp_path, lambda snap: snap)
    assert seed.error is None

    bad = dict(TEXT_META_A)
    bad["kind"] = "image"  # mismatch: text MIME but image kind
    result = commit(tmp_path, lambda snap: snap.add_source_meta(bad))

    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"


def test_concurrent_writes_serialize_and_preserve_all(tmp_path: Path):
    barrier = threading.Barrier(2)
    errors: list[dict[str, Any] | None] = [None, None]
    snapshots: list[Snapshot] = [None, None]  # type: ignore[list-item]

    def worker(slot: int) -> None:
        barrier.wait()
        def _append(snap: Snapshot) -> Snapshot:
            for i in range(10):
                snap = snap.add_task(_saved_task(slot * 100 + i))
            return snap
        result: CommitResult = commit(tmp_path, _append)
        errors[slot] = result.error
        snapshots[slot] = result.snapshot

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors[0] is None and errors[1] is None, f"errors={errors}"
    # Both commits succeeded without seeing each other's mid-state, proving each
    # reread the latest snapshot before mutating.
    final = load_snapshot(tmp_path)
    assert final.error is None
    assert len(final.snapshot.tasks) == 20
    expected_ids = {f"33333333-3333-4333-8333-{slot * 100 + i:012d}"
                    for slot in (0, 1) for i in range(10)}
    assert set(final.snapshot.tasks) == expected_ids


def test_snapshot_errors_reports_root_and_entity_problems():
    # Wrong root schema
    errors = snapshot_errors({"schemaVersion": 1, "sources": "x"})
    assert errors

    # Task key != id
    bad = {
        "schemaVersion": 1,
        "sources": {},
        "tasks": {
            "weird-key": {
                **_saved_task(1),
                "id": "88888888-8888-4888-8888-888888888888",
            }
        },
        "confirmedDraftSets": {},
    }
    assert snapshot_errors(bad)

    # Valid payload has no errors
    valid = {
        "schemaVersion": 1,
        "sources": {SOURCE_ID_A: TEXT_META_A},
        "tasks": {_saved_task(1)["id"]: _saved_task(1)},
        "confirmedDraftSets": {},
    }
    assert snapshot_errors(valid) == []


def test_commit_returns_error_when_root_invalid(tmp_path: Path):
    # Force an inconsistent mutate that mutates beyond allowed keys
    def _bad_mutate(snap: Snapshot) -> Snapshot:
        # Bypass by directly setting a non-camelCase key; this fails at serialize.
        snap.sources["oops"] = {"not": "valid"}
        return snap

    result = commit(tmp_path, _bad_mutate)
    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"
    assert not _main_present(tmp_path)


# ---------------------------------------------------------------- P05-01
# confirmedDraftSets value follows the contract shape {requestSha256, response}.

def test_confirmation_contract_shape_minimum_input():
    set_id = "00000001-1111-4111-8111-000000000001"
    contract_record = {
        "requestSha256": "d" * 64,
        "response": {"source": {}, "tasks": [], "savedAt": STAMP},
    }
    contract_payload = {
        "schemaVersion": 1,
        "sources": {},
        "tasks": {},
        "confirmedDraftSets": {set_id: contract_record},
    }
    # snapshot_errors accepts the contract shape (no value-internal draftSetId).
    assert snapshot_errors(contract_payload) == []

    # add_confirmation with an explicit draftSetId stores the value as the
    # exact contract shape (2 keys, no draftSetId inside the value).
    snap = Snapshot.empty().add_confirmation(
        {"draftSetId": set_id, **contract_record}
    )
    stored = snap.confirmed_draft_sets
    assert set(stored) == {set_id}
    assert stored[set_id] == contract_record

    # add_confirmation without draftSetId synthesizes a key but the value
    # still matches the contract shape.
    snap2 = Snapshot.empty().add_confirmation(contract_record)
    assert len(snap2.confirmed_draft_sets) == 1
    only_key = next(iter(snap2.confirmed_draft_sets))
    assert snap2.confirmed_draft_sets[only_key] == contract_record

    # Non-UUID draftSetId is rejected (contract says Record<UUID, ...>).
    with pytest.raises(ValueError):
        Snapshot.empty().add_confirmation(
            {"draftSetId": "not-a-uuid", **contract_record}
        )


def test_confirmation_stored_value_is_two_keys(tmp_path: Path):
    set_id = "00000002-2222-4222-8222-000000000002"
    record_input = {
        "draftSetId": set_id,
        "requestSha256": "e" * 64,
        "response": {"source": {}, "tasks": [], "savedAt": STAMP},
    }
    result = commit(
        tmp_path, lambda snap: snap.add_confirmation(record_input)
    )
    assert result.error is None
    on_disk = json.loads(_read_raw(tmp_path))
    value = on_disk["confirmedDraftSets"][set_id]
    assert set(value) == {"requestSha256", "response"}
    assert value == {"requestSha256": "e" * 64, "response": record_input["response"]}

    # Reload and verify shape is preserved.
    reloaded = load_snapshot(tmp_path)
    assert reloaded.error is None
    assert reloaded.snapshot.confirmed_draft_sets[set_id] == {
        "requestSha256": "e" * 64,
        "response": record_input["response"],
    }


def test_confirmation_payload_loads_from_disk(tmp_path: Path):
    set_id = "00000003-3333-4333-8333-000000000003"
    contract_payload = {
        "schemaVersion": 1,
        "sources": {},
        "tasks": {},
        "confirmedDraftSets": {
            set_id: {
                "requestSha256": "f" * 64,
                "response": {"source": {}, "tasks": [], "savedAt": STAMP},
            }
        },
    }
    _write_raw(tmp_path, json.dumps(contract_payload))
    loaded = load_snapshot(tmp_path)
    assert loaded.error is None
    assert set(loaded.snapshot.confirmed_draft_sets) == {set_id}
    assert loaded.snapshot.confirmed_draft_sets[set_id] == {
        "requestSha256": "f" * 64,
        "response": {"source": {}, "tasks": [], "savedAt": STAMP},
    }


# ---------------------------------------------------------------- P05-02
# Unknown root keys must be rejected (not silently dropped).

def test_unknown_root_key_is_rejected(tmp_path: Path):
    extra_payload = {
        "schemaVersion": 1,
        "sources": {},
        "tasks": {},
        "confirmedDraftSets": {},
        "futureField": {"keep": "me"},
    }
    _write_raw(tmp_path, json.dumps(extra_payload))
    pre = _read_raw(tmp_path)

    loaded = load_snapshot(tmp_path)
    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert _read_raw(tmp_path) == pre  # file untouched

    errors = snapshot_errors(extra_payload)
    assert any("futureField" in err for err in errors)


# ---------------------------------------------------------------- P05-03
# Precise injection: only the main replace fails. With the corrected order
# (main replace first, backup replace after), main AND .bak must both stay
# byte-identical to their pre-failure content. This is the QA R3-06 scenario.

def test_preexisting_bak_byte_unchanged_on_main_replace_failure(
    tmp_path: Path, monkeypatch
):
    # Round 1: first commit, no .bak yet.
    t1 = _saved_task(1)
    assert commit(tmp_path, lambda snap: snap.add_task(t1)).error is None
    v1_main = _read_raw(tmp_path)
    assert not _bak_present(tmp_path)

    # Round 2: second commit, creates .bak = v1.
    t2 = _saved_task(2)
    assert commit(tmp_path, lambda snap: snap.add_task(t2)).error is None
    v2_main = _read_raw(tmp_path)
    bak_before = (tmp_path / "state.json.bak").read_text(encoding="utf-8")
    assert bak_before == v1_main

    # Inject failure on the main replace only.
    import app.modules.tasks.storage.state_store as state_store_module

    replace_calls: list[tuple[str, str]] = []
    real_replace = state_store_module.os.replace

    def _maybe_boom(src, dst, *args, **kwargs):
        replace_calls.append((str(src), str(dst)))
        if str(src).endswith("state.json.tmp") and str(dst).endswith(
            "state.json"
        ):
            raise OSError("simulated replace failure")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(state_store_module.os, "replace", _maybe_boom)

    t3 = _saved_task(3)
    result = commit(tmp_path, lambda snap: snap.add_task(t3))

    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"
    assert result.warning is None
    # main byte-unchanged (v2)
    assert _read_raw(tmp_path) == v2_main
    # .bak byte-unchanged (still v1) -- the old backup generation survives.
    bak_now = (tmp_path / "state.json.bak").read_text(encoding="utf-8")
    assert bak_now == bak_before
    assert bak_now == v1_main
    # .bak was never replaced before the failed main swap.
    assert not any(
        src.endswith("state.json.bak.tmp") and dst.endswith("state.json.bak")
        for src, dst in replace_calls
    ), replace_calls
    # reload still shows v2 only
    reload = load_snapshot(tmp_path)
    assert reload.error is None
    assert set(reload.snapshot.tasks) == {t1["id"], t2["id"]}
    # No tmp leftovers.
    assert not (tmp_path / "state.json.tmp").exists()
    assert not (tmp_path / "state.json.bak.tmp").exists()


# Precise injection: main commit succeeds, then bak.tmp → bak fails.
# Defined semantics: main committed == commit succeeded; .bak keeps the older
# but still valid generation; the failure is reported in the optional
# warning field (no error code, no rollback).

def test_backup_replace_failure_after_main_commit_is_success(
    tmp_path: Path, monkeypatch
):
    t1 = _saved_task(1)
    assert commit(tmp_path, lambda snap: snap.add_task(t1)).error is None
    v1_main = _read_raw(tmp_path)

    t2 = _saved_task(2)
    assert commit(tmp_path, lambda snap: snap.add_task(t2)).error is None
    assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == v1_main

    import app.modules.tasks.storage.state_store as state_store_module

    replace_calls: list[tuple[str, str]] = []
    real_replace = state_store_module.os.replace

    def _boom_backup(src, dst, *args, **kwargs):
        replace_calls.append((str(src), str(dst)))
        if str(src).endswith("state.json.bak.tmp") and str(dst).endswith(
            "state.json.bak"
        ):
            raise OSError("simulated backup replace failure")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(state_store_module.os, "replace", _boom_backup)

    t3 = _saved_task(3)
    result = commit(tmp_path, lambda snap: snap.add_task(t3))

    # Commit is reported successful; the failure is advisory only.
    assert result.error is None
    assert result.snapshot is not None
    assert result.warning is not None
    assert "backup" in result.warning["code"]
    # main holds the new version
    on_disk = json.loads(_read_raw(tmp_path))
    assert set(on_disk["tasks"]) == {t1["id"], t2["id"], t3["id"]}
    # .bak keeps the older valid generation (v1), not the new v3
    bak_now = (tmp_path / "state.json.bak").read_text(encoding="utf-8")
    assert bak_now == v1_main
    # disk state is valid and reloads to the new version
    reload = load_snapshot(tmp_path)
    assert reload.error is None
    assert set(reload.snapshot.tasks) == {t1["id"], t2["id"], t3["id"]}
    # No tmp leftovers.
    assert not (tmp_path / "state.json.tmp").exists()
    assert not (tmp_path / "state.json.bak.tmp").exists()


# Staging the backup (writing bak.tmp) fails: main replace never runs, so
# main and .bak both stay byte-unchanged.

def test_backup_staging_failure_leaves_state_intact(tmp_path: Path):
    t1 = _saved_task(1)
    assert commit(tmp_path, lambda snap: snap.add_task(t1)).error is None

    t2 = _saved_task(2)
    assert commit(tmp_path, lambda snap: snap.add_task(t2)).error is None
    v2_main = _read_raw(tmp_path)
    bak_before = (tmp_path / "state.json.bak").read_text(encoding="utf-8")

    # Create a directory where bak.tmp must be written, so write_bytes fails.
    (tmp_path / "state.json.bak.tmp").mkdir()

    t3 = _saved_task(3)
    result = commit(tmp_path, lambda snap: snap.add_task(t3))

    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"
    assert result.warning is None
    # main and .bak byte-unchanged
    assert _read_raw(tmp_path) == v2_main
    assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == bak_before
    # reload still shows v2
    reload = load_snapshot(tmp_path)
    assert reload.error is None
    assert set(reload.snapshot.tasks) == {t1["id"], t2["id"]}
    # the tmp file is cleaned up
    assert not (tmp_path / "state.json.tmp").exists()


# Success path regression: after a successful commit, .bak holds the
# immediately previous main and nothing is left behind.

def test_successful_commit_backup_is_previous_main(tmp_path: Path):
    t1 = _saved_task(1)
    assert commit(tmp_path, lambda snap: snap.add_task(t1)).error is None
    # First write: no backup yet.
    assert not _bak_present(tmp_path)

    v1_main = _read_raw(tmp_path)
    t2 = _saved_task(2)
    result = commit(tmp_path, lambda snap: snap.add_task(t2))
    assert result.error is None
    assert result.warning is None
    assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == v1_main

    v2_main = _read_raw(tmp_path)
    t3 = _saved_task(3)
    result = commit(tmp_path, lambda snap: snap.add_task(t3))
    assert result.error is None
    assert result.warning is None
    assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == v2_main
    assert not (tmp_path / "state.json.tmp").exists()
    assert not (tmp_path / "state.json.bak.tmp").exists()
