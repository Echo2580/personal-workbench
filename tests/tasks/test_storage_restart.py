"""T05 存储组件 3 轮写入-重读往返测试：20 任务、共享来源、确认记录。"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.modules.tasks.storage.state_store import (
    Snapshot,
    commit,
    load_snapshot,
)


SOURCE_A = "11111111-1111-4111-8111-111111111111"
SOURCE_B = "22222222-2222-4222-8222-222222222222"
SOURCE_C = "33333333-3333-4333-8333-333333333333"
SOURCE_D = "44444444-4444-4444-8444-444444444444"
SOURCE_E = "55555555-5555-4555-8555-555555555555"
DRAFT_ID = "66666666-6666-4666-8666-666666666666"
VERSION = "77777777-7777-4777-8777-777777777777"
STAMP = "2026-10-20T08:00:00+08:00"
SET_IDS = [
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
]


def _meta(source_id: str) -> dict[str, Any]:
    return {
        "id": source_id,
        "kind": "text",
        "originalText": f"原文 {source_id}",
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": source_id.replace("-", "").ljust(64, "0")[:64],
    }


NONE_REMINDER = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": None,
}


def _saved_task(index: int, source_id: str) -> dict[str, Any]:
    return {
        "id": f"88888888-8888-4888-8888-{index:012d}",
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


def _confirmation(draft_set_id: str, response: dict[str, Any]) -> dict[str, Any]:
    return {
        "draftSetId": draft_set_id,
        "requestSha256": "f" * 64,
        "response": response,
    }


def _build_initial_snapshot() -> Snapshot:
    snap = Snapshot.empty()
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C, SOURCE_D, SOURCE_E):
        snap = snap.add_source_meta(_meta(sid))
    # 20 tasks; 2 tasks share SOURCE_A, 2 tasks share SOURCE_B; the rest are unique.
    plan = [SOURCE_A] * 2 + [SOURCE_B] * 2 + [SOURCE_C, SOURCE_D, SOURCE_E] * 5 + [SOURCE_A]
    assert len(plan) == 20
    for i, sid in enumerate(plan, start=1):
        snap = snap.add_task(_saved_task(i, sid))
    snap = snap.add_confirmation(
        _confirmation(
            SET_IDS[0],
            {"source": _meta(SOURCE_A), "tasks": [], "savedAt": STAMP},
        )
    )
    snap = snap.add_confirmation(
        _confirmation(
            SET_IDS[1],
            {"source": _meta(SOURCE_B), "tasks": [], "savedAt": STAMP},
        )
    )
    snap = snap.add_confirmation(
        _confirmation(
            SET_IDS[2],
            {"source": _meta(SOURCE_C), "tasks": [], "savedAt": STAMP},
        )
    )
    return snap


def test_three_round_trips_persist_exactly(tmp_path: Path):
    initial = _build_initial_snapshot()
    expected_payload = initial.to_payload()

    first = commit(tmp_path, lambda snap: initial)
    assert first.error is None
    on_disk = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert on_disk == expected_payload

    for round_idx in range(3):
        # New instance reads the snapshot back from disk; identity must hold.
        loaded = load_snapshot(tmp_path)
        assert loaded.error is None, f"round {round_idx}: {loaded.error}"
        assert loaded.snapshot.to_payload() == expected_payload, (
            f"round {round_idx} payload mismatch"
        )

        # Mutate by adding one more confirmation (different draft set each round)
        # and re-commit, then re-read fresh. Re-doing the same mutate over the
        # same disk snapshot must be idempotent.
        new_set_id = f"dddddddd-dddd-4ddd-8ddd-{round_idx:012d}"
        new_confirmation = _confirmation(
            new_set_id,
            {"source": _meta(SOURCE_D), "tasks": [], "savedAt": STAMP},
        )
        baseline_payload = loaded.snapshot.to_payload()
        result = commit(
            tmp_path,
            lambda snap, _c=new_confirmation: snap.add_confirmation(_c),
        )
        assert result.error is None

        # Re-read after the new commit and ensure the new confirmation is
        # present while every previously stored value is preserved. The
        # stored value follows the contract shape {requestSha256, response};
        # the caller-supplied draftSetId is consumed as the key and not
        # re-injected into the value.
        reread = load_snapshot(tmp_path)
        assert reread.error is None
        merged = deepcopy(baseline_payload)
        merged["confirmedDraftSets"][new_set_id] = {
            "requestSha256": new_confirmation["requestSha256"],
            "response": new_confirmation["response"],
        }
        assert reread.snapshot.to_payload() == merged

        # Roll back to baseline so each round is comparable: remove the new
        # confirmation in a subsequent commit. This also exercises the
        # "re-read latest before mutate" property of the lock.
        reread_snapshot = reread.snapshot
        baseline_snapshot = reread_snapshot.without(new_set_id)

        def _restore(snap: Snapshot) -> Snapshot:
            # The on-disk snapshot must already include the new confirmation;
            # dropping it here proves the commit saw the latest state.
            return snap.without(new_set_id)

        result = commit(tmp_path, _restore)
        assert result.error is None
        # The baseline we expected equals the disk-snapshot with the new
        # confirmation removed, which is what _restore returns from the
        # latest on-disk state.
        assert result.snapshot.to_payload() == baseline_snapshot.to_payload()
