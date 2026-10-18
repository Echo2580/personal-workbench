"""构造样本测试 T08 提醒运行时服务层（过期扫描、六步顺序、due 过滤）。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.modules.tasks.services.reminder_runtime import (
    ReminderSession,
    SessionRegistry,
    acknowledge,
    due_reminders,
    expire_stale_reminders,
    open_session,
    remember_session,
)
from app.modules.tasks.storage import Snapshot, commit, load_snapshot


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=SHANGHAI)
STARTED = "2026-10-16T11:59:00+08:00"
DUE_MOMENT = "2026-10-16T11:59:30+08:00"
LATER = "2026-10-16T12:30:00+08:00"
EARLIER = "2026-10-16T11:00:00+08:00"

SOURCE_A = "11111111-1111-4111-8111-111111111111"
DRAFT_ID = "33333333-3333-4333-8333-333333333333"
VERSION = "55555555-5555-4555-8555-555555555555"
OTHER_VERSION = "66666666-6666-4666-8666-666666666666"
SESSION_A = "aaaaaaaa-0000-4000-8000-000000000001"
SESSION_B = "bbbbbbbb-0000-4000-8000-000000000002"


def source_payload(source_id: str = SOURCE_A) -> dict[str, Any]:
    return {
        "id": source_id,
        "kind": "text",
        "originalText": "请交报告",
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": "2026-10-16T08:00:00+08:00",
        "contentSha256": "a" * 64,
    }


def manual_reminder(
    moment: str,
    *,
    state: str = "scheduled",
    acknowledged_at: str | None = None,
    revision: str = VERSION,
) -> dict[str, Any]:
    scheduled = moment if state in ("scheduled", "acknowledged", "expired") else None
    return {
        "mode": "manual",
        "requestedAt": moment,
        "scheduledAt": scheduled,
        "relativeTo": None,
        "offsetMinutes": None,
        "state": state,
        "acknowledgedAt": acknowledged_at,
        "revision": revision,
    }


def none_reminder(revision: str = VERSION) -> dict[str, Any]:
    return {
        "mode": "none",
        "requestedAt": None,
        "scheduledAt": None,
        "relativeTo": None,
        "offsetMinutes": None,
        "state": "not_set",
        "acknowledgedAt": None,
        "revision": revision,
    }


def blocked_reminder(revision: str = VERSION) -> dict[str, Any]:
    return {
        "mode": "relative",
        "requestedAt": None,
        "scheduledAt": None,
        "relativeTo": "due",
        "offsetMinutes": 30,
        "state": "blocked",
        "acknowledgedAt": None,
        "revision": revision,
    }


def task_payload(
    task_id: str,
    *,
    reminder: dict[str, Any],
    status: str = "open",
    title: str = "交报告",
    due: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "draftId": DRAFT_ID,
        "sourceId": SOURCE_A,
        "title": title,
        "startTime": None,
        "dueTime": due,
        "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告",
        "reviewIssues": [],
        "status": status,
        "reminder": reminder,
        "createdAt": "2026-10-16T08:00:00+08:00",
        "updatedAt": "2026-10-16T08:00:00+08:00",
    }


def seed(root: Path, *tasks: dict[str, Any]) -> Snapshot:
    def _mutate(snap: Snapshot) -> Snapshot:
        snap = snap.add_source_meta(source_payload())
        for task in tasks:
            snap = snap.add_task(deepcopy(task))
        return snap

    result = commit(root, _mutate)
    assert result.error is None, result.error
    return result.snapshot


def registry(session_id: str = SESSION_A, started_at: str = STARTED) -> SessionRegistry:
    reg = SessionRegistry()
    remember_session(reg, ReminderSession(session_id=session_id, started_at=started_at))
    return reg


# ---------------------------------------------------------------- 过期扫描

def test_expire_scan_only_touches_open_scheduled_before_threshold(tmp_path: Path):
    ids = {
        "stale": "00000001-0000-4000-8000-000000000001",
        "future": "00000002-0000-4000-8000-000000000002",
        "blocked": "00000003-0000-4000-8000-000000000003",
        "not_set": "00000004-0000-4000-8000-000000000004",
        "acked": "00000005-0000-4000-8000-000000000005",
        "cancelled": "00000006-0000-4000-8000-000000000006",
        "expired": "00000007-0000-4000-8000-000000000007",
        "completed": "00000008-0000-4000-8000-000000000008",
    }
    seed(
        tmp_path,
        task_payload(ids["stale"], reminder=manual_reminder(EARLIER)),
        task_payload(ids["future"], reminder=manual_reminder(LATER)),
        task_payload(ids["blocked"], reminder=blocked_reminder()),
        task_payload(ids["not_set"], reminder=none_reminder()),
        task_payload(
            ids["acked"],
            reminder=manual_reminder(
                DUE_MOMENT, state="acknowledged", acknowledged_at=DUE_MOMENT
            ),
        ),
        task_payload(
            ids["cancelled"],
            reminder=manual_reminder(DUE_MOMENT, state="cancelled"),
        ),
        task_payload(
            ids["expired"], reminder=manual_reminder(DUE_MOMENT, state="expired")
        ),
        task_payload(
            ids["completed"],
            status="completed",
            reminder=manual_reminder(DUE_MOMENT, state="cancelled"),
        ),
    )
    before = {
        tid: task.model_dump(mode="json", by_alias=True)
        for tid, task in load_snapshot(tmp_path).snapshot.tasks.items()
    }

    snapshot = load_snapshot(tmp_path).snapshot
    updated, count, changed_ids = expire_stale_reminders(snapshot, STARTED)

    assert count == 1
    assert changed_ids == sorted([ids["stale"]])
    stale = updated.tasks[ids["stale"]].reminder
    assert stale.state == "expired"
    # 其余字段原样：scheduledAt / revision / acknowledgedAt 未变
    assert stale.scheduled_at == EARLIER
    assert stale.revision == VERSION
    assert stale.requested_at == EARLIER

    after = {
        tid: task.model_dump(mode="json", by_alias=True)
        for tid, task in updated.tasks.items()
    }
    for key in ids:
        if key == "stale":
            continue
        assert after[ids[key]] == before[ids[key]], key


def test_expire_scan_with_nothing_to_do_returns_unchanged(tmp_path: Path):
    seed(tmp_path, task_payload("00000009-0000-4000-8000-000000000009", reminder=manual_reminder(LATER)))
    snapshot = load_snapshot(tmp_path).snapshot

    updated, count, changed_ids = expire_stale_reminders(snapshot, STARTED)

    assert count == 0
    assert changed_ids == []
    assert updated is snapshot or updated.to_payload() == snapshot.to_payload()


def test_expire_scan_compares_moments_with_fractional_seconds(tmp_path: Path):
    just_before = "2026-10-16T11:58:59.999999+08:00"
    just_after = "2026-10-16T11:59:00.000001+08:00"
    seed(
        tmp_path,
        task_payload("00000010-0000-4000-8000-000000000010", reminder=manual_reminder(just_before)),
        task_payload("00000011-0000-4000-8000-000000000011", reminder=manual_reminder(just_after)),
    )
    snapshot = load_snapshot(tmp_path).snapshot

    updated, count, changed_ids = expire_stale_reminders(snapshot, STARTED)

    assert count == 1
    assert changed_ids == ["00000010-0000-4000-8000-000000000010"]
    # 边界相等不算过期
    assert updated.tasks["00000011-0000-4000-8000-000000000011"].reminder.state == "scheduled"
    # 原字符串形式保留
    assert (
        updated.tasks["00000010-0000-4000-8000-000000000010"].reminder.scheduled_at
        == just_before
    )


# ---------------------------------------------------------------- 会话

def test_open_session_returns_three_fields(tmp_path: Path):
    reg = SessionRegistry()
    outcome = open_session(tmp_path, reg, NOW)

    assert outcome.status_code == 200
    assert set(outcome.body) == {"sessionId", "startedAt", "intervalSeconds"}
    assert outcome.body["startedAt"] == NOW.isoformat()
    assert outcome.body["intervalSeconds"] == 5
    assert reg.current is not None
    assert reg.current.session_id == outcome.body["sessionId"]


def test_open_session_supersedes_previous(tmp_path: Path):
    reg = SessionRegistry()
    first = open_session(tmp_path, reg, NOW).body
    second = open_session(tmp_path, reg, NOW + timedelta(seconds=10)).body

    assert second["sessionId"] != first["sessionId"]
    assert first["sessionId"] in reg.superseded
    assert reg.current.session_id == second["sessionId"]


def test_open_session_applies_expiry_inside_commit(tmp_path: Path):
    reg = SessionRegistry()
    open_session(tmp_path, reg, NOW)
    # 会话建立后写入一条早于新会话 startedAt 的 scheduled
    seed(tmp_path, task_payload("00000012-0000-4000-8000-000000000012", reminder=manual_reminder(EARLIER)))

    later = NOW + timedelta(minutes=5)
    outcome = open_session(tmp_path, reg, later)

    assert outcome.status_code == 200
    assert outcome.expired == 1
    assert (
        load_snapshot(tmp_path).snapshot.tasks["00000012-0000-4000-8000-000000000012"].reminder.state
        == "expired"
    )


# ---------------------------------------------------------------- due 过滤

def test_due_filters_interval_state_and_status(tmp_path: Path):
    reg = registry()
    seed(
        tmp_path,
        task_payload("00000013-0000-4000-8000-000000000013", reminder=manual_reminder(DUE_MOMENT), title="区间内"),
        task_payload("00000014-0000-4000-8000-000000000014", reminder=manual_reminder(EARLIER), title="早于 startedAt"),
        task_payload("00000015-0000-4000-8000-000000000015", reminder=manual_reminder(LATER), title="晚于 now"),
        task_payload("00000016-0000-4000-8000-000000000016", reminder=blocked_reminder(), title="阻塞"),
        task_payload("00000017-0000-4000-8000-000000000017", reminder=none_reminder(), title="未设置"),
        task_payload(
            "00000018-0000-4000-8000-000000000018",
            status="completed",
            reminder=manual_reminder(DUE_MOMENT, state="cancelled"),
            title="已完成",
        ),
    )

    outcome = due_reminders(tmp_path, reg, SESSION_A, NOW)

    assert outcome.status_code == 200
    assert outcome.body["checkedAt"] == NOW.isoformat()
    items = outcome.body["reminders"]
    assert len(items) == 1
    item = items[0]
    assert item["taskId"] == "00000013-0000-4000-8000-000000000013"
    assert item["title"] == "区间内"
    assert item["sourceId"] == SOURCE_A
    assert item["scheduledAt"] == DUE_MOMENT
    assert item["state"] == "scheduled"
    assert item["reminderVersion"] == VERSION
    assert set(item) == {
        "taskId",
        "title",
        "sourceId",
        "scheduledAt",
        "state",
        "reminderVersion",
    }


def test_due_boundaries_are_inclusive(tmp_path: Path):
    reg = registry()
    seed(
        tmp_path,
        task_payload("00000019-0000-4000-8000-000000000019", reminder=manual_reminder(STARTED)),
        task_payload("00000020-0000-4000-8000-000000000020", reminder=manual_reminder(NOW.isoformat())),
    )

    outcome = due_reminders(tmp_path, reg, SESSION_A, NOW)

    ids = {item["taskId"] for item in outcome.body["reminders"]}
    assert ids == {
        "00000019-0000-4000-8000-000000000019",
        "00000020-0000-4000-8000-000000000020",
    }


def test_due_rejects_superseded_and_unknown_sessions(tmp_path: Path):
    reg = registry()
    remember_session(reg, ReminderSession(session_id=SESSION_B, started_at=STARTED))

    superseded = due_reminders(tmp_path, reg, SESSION_A, NOW)
    assert superseded.status_code == 409
    assert superseded.error.code == "reminder_session_superseded"

    unknown = due_reminders(tmp_path, reg, "cccccccc-0000-4000-8000-000000000003", NOW)
    assert unknown.status_code == 404
    assert unknown.error.code == "reminder_session_not_found"


# ---------------------------------------------------------------- §4.3 六步

def ack_ready_task(task_id: str, moment: str = DUE_MOMENT) -> dict[str, Any]:
    return task_payload(task_id, reminder=manual_reminder(moment))


def test_step1_task_not_found(tmp_path: Path):
    reg = registry()
    snapshot = Snapshot.empty()

    outcome = acknowledge(
        snapshot, "00000021-0000-4000-8000-000000000021", SESSION_A, VERSION, NOW, reg
    )

    assert outcome.step == 1
    assert outcome.status_code == 404
    assert outcome.error.code == "task_not_found"


def test_step2_version_conflict_before_replay(tmp_path: Path):
    reg = registry()
    seed(
        tmp_path,
        task_payload(
            "00000022-0000-4000-8000-000000000022",
            reminder=manual_reminder(
                DUE_MOMENT, state="acknowledged", acknowledged_at=DUE_MOMENT
            ),
        ),
    )
    snapshot = load_snapshot(tmp_path).snapshot

    outcome = acknowledge(
        snapshot,
        "00000022-0000-4000-8000-000000000022",
        SESSION_A,
        OTHER_VERSION,
        NOW,
        reg,
    )

    assert outcome.step == 2
    assert outcome.status_code == 409
    assert outcome.error.code == "reminder_version_conflict"


def test_step3_replay_precedes_session_check(tmp_path: Path):
    """第 3 步优先于第 5 步：已 acknowledged + 完全未知的会话 ID → 200 回放。"""
    reg = registry()
    seed(
        tmp_path,
        task_payload(
            "00000023-0000-4000-8000-000000000023",
            reminder=manual_reminder(
                DUE_MOMENT, state="acknowledged", acknowledged_at=DUE_MOMENT
            ),
        ),
    )
    snapshot = load_snapshot(tmp_path).snapshot

    outcome = acknowledge(
        snapshot,
        "00000023-0000-4000-8000-000000000023",
        "dddddddd-0000-4000-8000-000000000004",  # 未知会话
        VERSION,
        NOW,
        reg,
    )

    assert outcome.step == 3
    assert outcome.status_code == 200
    assert outcome.task is None  # 只读，不写状态
    assert outcome.body == {
        "taskId": "00000023-0000-4000-8000-000000000023",
        "reminderVersion": VERSION,
        "state": "acknowledged",
        "acknowledgedAt": DUE_MOMENT,
    }


@pytest.mark.parametrize(
    "reminder",
    [
        manual_reminder(DUE_MOMENT, state="expired"),
        manual_reminder(DUE_MOMENT, state="cancelled"),
        blocked_reminder(),
        none_reminder(),
    ],
)
def test_step4_non_acknowledgeable_states(tmp_path: Path, reminder: dict):
    reg = registry()
    task_id = "00000024-0000-4000-8000-000000000024"
    seed(tmp_path, task_payload(task_id, reminder=reminder))
    snapshot = load_snapshot(tmp_path).snapshot

    outcome = acknowledge(snapshot, task_id, SESSION_A, VERSION, NOW, reg)

    assert outcome.step == 4
    assert outcome.status_code == 409
    assert outcome.error.code == "reminder_not_acknowledgeable"


def test_step4_scheduled_with_invalid_conditions(tmp_path: Path):
    """第 4 步的后半：scheduled 但任务不是 open 或条件无效 → 409。

    领域模型不允许 completed+scheduled 或 scheduled+待核对条件落盘，因此这里
    用 model_copy(update=...) 在内存中构造"历史/损坏数据"来覆盖防御分支。
    """
    reg = registry()
    task_id = "00000025-0000-4000-8000-000000000025"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(DUE_MOMENT)))
    snapshot = load_snapshot(tmp_path).snapshot
    valid_task = snapshot.tasks[task_id]

    # (a) 任务非 open
    not_open = valid_task.model_copy(update={"status": "completed"})
    broken = Snapshot(
        schema_version=snapshot.schema_version,
        sources=snapshot.sources,
        tasks={task_id: not_open},
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )
    outcome = acknowledge(broken, task_id, SESSION_A, VERSION, NOW, reg)
    assert outcome.step == 4
    assert outcome.status_code == 409
    assert outcome.error.code == "reminder_not_acknowledgeable"

    # (b) 适用性待确认
    from app.modules.tasks.domain import Applicability

    pending = valid_task.model_copy(
        update={
            "applicability": Applicability(
                text="仅本班同学", status="needs_confirmation"
            )
        }
    )
    broken2 = Snapshot(
        schema_version=snapshot.schema_version,
        sources=snapshot.sources,
        tasks={task_id: pending},
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )
    outcome2 = acknowledge(broken2, task_id, SESSION_A, VERSION, NOW, reg)
    assert outcome2.step == 4
    assert outcome2.status_code == 409
    assert outcome2.error.code == "reminder_not_acknowledgeable"

    # (c) 已出现的时间待核对
    from app.modules.tasks.domain import TimeInfo

    waiting = valid_task.model_copy(
        update={
            "start_time": TimeInfo(
                rawExpression="周五前",
                precision="relative",
                resolvedValue=None,
                timeZone="Asia/Shanghai",
                status="needs_confirmation",
            )
        }
    )
    broken3 = Snapshot(
        schema_version=snapshot.schema_version,
        sources=snapshot.sources,
        tasks={task_id: waiting},
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )
    outcome3 = acknowledge(broken3, task_id, SESSION_A, VERSION, NOW, reg)
    assert outcome3.step == 4
    assert outcome3.status_code == 409
    assert outcome3.error.code == "reminder_not_acknowledgeable"


def test_step5_session_branches(tmp_path: Path):
    task_id = "00000026-0000-4000-8000-000000000026"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(DUE_MOMENT)))
    snapshot = load_snapshot(tmp_path).snapshot

    # 未知会话 → 404
    empty_reg = SessionRegistry()
    unknown = acknowledge(snapshot, task_id, SESSION_A, VERSION, NOW, empty_reg)
    assert unknown.step == 5
    assert unknown.status_code == 404
    assert unknown.error.code == "reminder_session_not_found"

    # 已取代 → 409
    superseded_reg = registry()
    remember_session(
        superseded_reg, ReminderSession(session_id=SESSION_B, started_at=STARTED)
    )
    superseded = acknowledge(snapshot, task_id, SESSION_A, VERSION, NOW, superseded_reg)
    assert superseded.step == 5
    assert superseded.status_code == 409
    assert superseded.error.code == "reminder_session_superseded"

    # 当前会话但尚未到期 → 409 not_acknowledgeable
    early_reg = registry(started_at="2026-10-16T12:30:00+08:00")
    not_yet = acknowledge(snapshot, task_id, SESSION_A, VERSION, NOW, early_reg)
    assert not_yet.step == 5
    assert not_yet.status_code == 409
    assert not_yet.error.code == "reminder_not_acknowledgeable"


def test_step5_rejects_session_after_scheduled_moment(tmp_path: Path):
    """scheduledAt 早于会话 startedAt（不在区间）→ 409。"""
    task_id = "00000027-0000-4000-8000-000000000027"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(EARLIER)))
    snapshot = load_snapshot(tmp_path).snapshot
    reg = registry()

    outcome = acknowledge(snapshot, task_id, SESSION_A, VERSION, NOW, reg)

    assert outcome.step == 5
    assert outcome.status_code == 409
    assert outcome.error.code == "reminder_not_acknowledgeable"


def test_step6_produces_task_with_acknowledged_state_and_same_revision(tmp_path: Path):
    task_id = "00000028-0000-4000-8000-000000000028"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(DUE_MOMENT)))
    snapshot = load_snapshot(tmp_path).snapshot
    reg = registry()

    outcome = acknowledge(snapshot, task_id, SESSION_A, VERSION, NOW, reg)

    assert outcome.step == 6
    assert outcome.status_code == 200
    assert outcome.task is not None
    assert outcome.task.reminder.state == "acknowledged"
    assert outcome.task.reminder.acknowledged_at == NOW.isoformat()
    assert outcome.task.reminder.revision == VERSION      # 版本不变
    assert outcome.task.reminder.scheduled_at == DUE_MOMENT
    assert outcome.body == {
        "taskId": task_id,
        "reminderVersion": VERSION,
        "state": "acknowledged",
        "acknowledgedAt": NOW.isoformat(),
    }
