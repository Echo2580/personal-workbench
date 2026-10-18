"""构造样本测试 T08 提醒会话三端点（会话生命周期、due 区间、§4.3 六步、§6 生命周期）。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tasks_test_app import create_app
from app.modules.tasks.storage import Snapshot, commit, load_snapshot


SHANGHAI = timezone(timedelta(hours=8))
SOURCE_A = "11111111-1111-4111-8111-111111111111"
DRAFT_ID = "33333333-3333-4333-8333-333333333333"
VERSION = "55555555-5555-4555-8555-555555555555"
OTHER_VERSION = "66666666-6666-4666-8666-666666666666"
UNKNOWN_TASK = "99999999-9999-4999-8999-999999999999"
UNKNOWN_SESSION = "dddddddd-0000-4000-8000-000000000004"


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


NONE_REMINDER = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": VERSION,
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


def resolved_due(value: str) -> dict[str, Any]:
    return {
        "rawExpression": "10月20日10:00",
        "precision": "datetime",
        "resolvedValue": value,
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def seed(root: Path, *tasks: dict[str, Any]) -> None:
    def _mutate(snap: Snapshot) -> Snapshot:
        if SOURCE_A not in snap.sources:
            snap = snap.add_source_meta(source_payload())
        for task in tasks:
            snap = snap.add_task(deepcopy(task))
        return snap

    result = commit(root, _mutate)
    assert result.error is None, result.error


def seed_stale_scheduled(root: Path, task_id: str = "00000099-0000-4000-8000-000000000099") -> str:
    """种一条 scheduledAt 早于任何新会话 startedAt 的 open 任务（必有过期项）。"""
    stale = "2020-01-01T00:00:00+08:00"
    seed(
        root,
        task_payload(
            task_id,
            reminder=manual_reminder(stale),
            title="过期提醒",
        ),
    )
    return task_id


def client_for(root: Path) -> TestClient:
    return TestClient(create_app(root))


def open_session(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/reminder-sessions")
    assert response.status_code == 200, response.text
    return response.json()


def stored_task(root: Path, task_id: str) -> dict[str, Any]:
    return load_snapshot(root).snapshot.tasks[task_id].model_dump(
        mode="json", by_alias=True
    )


# ---------------------------------------------------------------- 会话生命周期

def test_create_session_returns_three_fields(tmp_path: Path):
    client = client_for(tmp_path)

    response = client.post("/api/v1/reminder-sessions")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sessionId", "startedAt", "intervalSeconds"}
    assert body["intervalSeconds"] == 5
    started = datetime.fromisoformat(body["startedAt"])
    assert started.utcoffset() == timedelta(hours=8)


def test_new_session_supersedes_previous(tmp_path: Path):
    client = client_for(tmp_path)
    first = open_session(client)
    second = open_session(client)

    assert first["sessionId"] != second["sessionId"]

    due = client.get(f"/api/v1/reminder-sessions/{first['sessionId']}/due")
    assert due.status_code == 409
    assert due.json()["error"]["code"] == "reminder_session_superseded"

    seeded = seed(tmp_path, task_payload("00000001-0000-4000-8000-000000000001", reminder=manual_reminder(second["startedAt"])))
    ack = client.post(
        f"/api/v1/reminders/00000001-0000-4000-8000-000000000001/acknowledgment",
        json={"sessionId": first["sessionId"], "reminderVersion": VERSION},
    )
    assert ack.status_code == 409
    assert ack.json()["error"]["code"] == "reminder_session_superseded"


def test_unknown_session_after_restart_is_404(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)

    restarted = client_for(tmp_path)  # 新 app 实例 = 重启

    due = restarted.get(f"/api/v1/reminder-sessions/{session['sessionId']}/due")
    assert due.status_code == 404
    assert due.json()["error"]["code"] == "reminder_session_not_found"


def test_session_creation_expires_only_stale_scheduled(tmp_path: Path):
    client = client_for(tmp_path)
    first = open_session(client)
    started = datetime.fromisoformat(first["startedAt"])
    stale = (started - timedelta(minutes=5)).isoformat()
    future = (started + timedelta(hours=1)).isoformat()

    seed(
        tmp_path,
        task_payload("00000002-0000-4000-8000-000000000002", reminder=manual_reminder(stale), title="过期"),
        task_payload("00000003-0000-4000-8000-000000000003", reminder=manual_reminder(future), title="未来"),
        task_payload("00000004-0000-4000-8000-000000000004", reminder=NONE_REMINDER, title="未设置"),
        task_payload(
            "00000005-0000-4000-8000-000000000005",
            reminder=manual_reminder(stale, state="cancelled"),
            title="已取消",
        ),
    )
    before = {tid: stored_task(tmp_path, tid) for tid in (
        "00000002-0000-4000-8000-000000000002",
        "00000003-0000-4000-8000-000000000003",
        "00000004-0000-4000-8000-000000000004",
        "00000005-0000-4000-8000-000000000005",
    )}

    open_session(client)  # 第二次会话触发扫描

    after = {tid: stored_task(tmp_path, tid) for tid in before}
    # 只有 scheduled 且早于新 startedAt 的项变 expired
    assert after["00000002-0000-4000-8000-000000000002"]["reminder"]["state"] == "expired"
    assert (
        after["00000002-0000-4000-8000-000000000002"]["reminder"]["scheduledAt"]
        == before["00000002-0000-4000-8000-000000000002"]["reminder"]["scheduledAt"]
    )
    assert (
        after["00000002-0000-4000-8000-000000000002"]["reminder"]["revision"] == VERSION
    )
    for tid in (
        "00000003-0000-4000-8000-000000000003",
        "00000004-0000-4000-8000-000000000004",
        "00000005-0000-4000-8000-000000000005",
    ):
        assert after[tid] == before[tid], tid


# ---------------------------------------------------------------- due 查询

def test_due_returns_only_items_inside_the_session_interval(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)
    started = session["startedAt"]
    started_dt = datetime.fromisoformat(started)
    earlier = (started_dt - timedelta(minutes=1)).isoformat()
    later = (started_dt + timedelta(hours=2)).isoformat()

    seed(
        tmp_path,
        task_payload("00000006-0000-4000-8000-000000000006", reminder=manual_reminder(started), title="区间内"),
        task_payload("00000007-0000-4000-8000-000000000007", reminder=manual_reminder(earlier), title="早于会话"),
        task_payload("00000008-0000-4000-8000-000000000008", reminder=manual_reminder(later), title="未到期"),
        task_payload("00000009-0000-4000-8000-000000000009", reminder=NONE_REMINDER, title="未设置"),
        task_payload(
            "0000000a-0000-4000-8000-00000000000a",
            status="completed",
            reminder=manual_reminder(started, state="cancelled"),
            title="已完成",
        ),
    )

    response = client.get(f"/api/v1/reminder-sessions/{session['sessionId']}/due")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"checkedAt", "reminders"}
    checked_at = datetime.fromisoformat(body["checkedAt"])
    assert checked_at.utcoffset() == timedelta(hours=8)
    assert len(body["reminders"]) == 1
    item = body["reminders"][0]
    assert item == {
        "taskId": "00000006-0000-4000-8000-000000000006",
        "title": "区间内",
        "sourceId": SOURCE_A,
        "scheduledAt": started,
        "state": "scheduled",
        "reminderVersion": VERSION,
    }


# ---------------------------------------------------------------- §4.3 六步

def test_ack_missing_task_is_404(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)

    response = client.post(
        f"/api/v1/reminders/{UNKNOWN_TASK}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"


def test_ack_old_version_is_409(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "0000000b-0000-4000-8000-00000000000b"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(session["startedAt"])))

    response = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": OTHER_VERSION},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reminder_version_conflict"


def test_ack_replay_wins_over_session_check(tmp_path: Path):
    """第 3 步优先于第 5 步：已 acknowledged + 未知会话 → 200 回放原时间戳。"""
    client = client_for(tmp_path)
    task_id = "0000000c-0000-4000-8000-00000000000c"
    acked_at = "2026-10-16T11:00:00+08:00"
    seed(
        tmp_path,
        task_payload(
            task_id,
            reminder=manual_reminder(
                "2026-10-16T10:59:00+08:00",
                state="acknowledged",
                acknowledged_at=acked_at,
            ),
        ),
    )
    before = stored_task(tmp_path, task_id)

    response = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": UNKNOWN_SESSION, "reminderVersion": VERSION},
    )

    assert response.status_code == 200
    assert response.json() == {
        "taskId": task_id,
        "reminderVersion": VERSION,
        "state": "acknowledged",
        "acknowledgedAt": acked_at,
    }
    # 只读回放：状态与时间戳均未改变
    assert stored_task(tmp_path, task_id) == before


def test_ack_replay_after_restart(tmp_path: Path):
    client = client_for(tmp_path)
    task_id = "0000000d-0000-4000-8000-00000000000d"
    acked_at = "2026-10-16T11:00:00+08:00"
    seed(
        tmp_path,
        task_payload(
            task_id,
            reminder=manual_reminder(
                "2026-10-16T10:59:00+08:00",
                state="acknowledged",
                acknowledged_at=acked_at,
            ),
        ),
    )

    restarted = client_for(tmp_path)
    response = restarted.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": UNKNOWN_SESSION, "reminderVersion": VERSION},
    )

    assert response.status_code == 200
    assert response.json()["acknowledgedAt"] == acked_at


@pytest.mark.parametrize(
    "reminder",
    [
        manual_reminder("2026-10-16T11:00:00+08:00", state="expired"),
        manual_reminder("2026-10-16T11:00:00+08:00", state="cancelled"),
        {
            "mode": "relative",
            "requestedAt": None,
            "scheduledAt": None,
            "relativeTo": "due",
            "offsetMinutes": 30,
            "state": "blocked",
            "acknowledgedAt": None,
            "revision": VERSION,
        },
        NONE_REMINDER,
    ],
)
def test_ack_non_acknowledgeable_states(tmp_path: Path, reminder: dict):
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "0000000e-0000-4000-8000-00000000000e"
    seed(tmp_path, task_payload(task_id, reminder=reminder))

    response = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reminder_not_acknowledgeable"


def test_ack_not_yet_due_is_409(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "0000000f-0000-4000-8000-00000000000f"
    future = (datetime.fromisoformat(session["startedAt"]) + timedelta(hours=2)).isoformat()
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(future)))

    response = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reminder_not_acknowledgeable"


def test_ack_success_writes_acknowledged_with_same_revision(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "00000010-0000-4000-8000-000000000010"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(session["startedAt"])))

    response = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"taskId", "reminderVersion", "state", "acknowledgedAt"}
    assert body["state"] == "acknowledged"
    assert datetime.fromisoformat(body["acknowledgedAt"]).utcoffset() == timedelta(hours=8)

    # 磁盘与 GET 一致；revision 不变
    task = stored_task(tmp_path, task_id)
    assert task["reminder"]["state"] == "acknowledged"
    assert task["reminder"]["acknowledgedAt"] == body["acknowledgedAt"]
    assert task["reminder"]["revision"] == VERSION
    detail = client.get(f"/api/v1/tasks/{task_id}")
    assert detail.json()["task"]["reminder"]["state"] == "acknowledged"

    # 重复确认同版本 → 200 回放原时间戳
    repeat = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )
    assert repeat.status_code == 200
    assert repeat.json() == body

    # 已确认的项不再进入 due
    due = client.get(f"/api/v1/reminder-sessions/{session['sessionId']}/due")
    assert due.json()["reminders"] == []


def test_ack_relative_reminder_due_and_acknowledged(tmp_path: Path):
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "00000011-0000-4000-8000-000000000011"
    started_dt = datetime.fromisoformat(session["startedAt"])
    # scheduledAt = 会话起点（区间下界，含）；relative 基准 dueTime = scheduledAt + 30min
    scheduled_moment = session["startedAt"]
    due_time = (started_dt + timedelta(minutes=30)).isoformat()
    reminder = {
        "mode": "relative",
        "requestedAt": None,
        "scheduledAt": scheduled_moment,
        "relativeTo": "due",
        "offsetMinutes": 30,
        "state": "scheduled",
        "acknowledgedAt": None,
        "revision": VERSION,
    }
    seed(
        tmp_path,
        task_payload(
            task_id,
            due=resolved_due(due_time),
            reminder=reminder,
        ),
    )

    due = client.get(f"/api/v1/reminder-sessions/{session['sessionId']}/due")
    assert due.status_code == 200
    assert [i["taskId"] for i in due.json()["reminders"]] == [task_id]
    assert due.json()["reminders"][0]["scheduledAt"] == scheduled_moment

    ack = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["state"] == "acknowledged"
    # relative 终态不被后来的任务时间变化重算
    task = stored_task(tmp_path, task_id)
    assert task["reminder"]["scheduledAt"] == scheduled_moment
    assert task["reminder"]["revision"] == VERSION


# ---------------------------------------------------------------- 400 校验

@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sessionId": UNKNOWN_SESSION},
        {"reminderVersion": VERSION},
        {"sessionId": None, "reminderVersion": VERSION},
        {"sessionId": UNKNOWN_SESSION, "reminderVersion": None},
        {"sessionId": "not-a-uuid", "reminderVersion": VERSION},
        {"sessionId": UNKNOWN_SESSION, "reminderVersion": "not-a-uuid"},
        {"sessionId": UNKNOWN_SESSION.upper(), "reminderVersion": VERSION},
        {"sessionId": UNKNOWN_SESSION, "reminderVersion": VERSION, "extra": 1},
        {"sessionId": UNKNOWN_SESSION, "reminderVersion": VERSION, "state": "acknowledged"},
    ],
)
def test_ack_request_shape_is_400(tmp_path: Path, body: dict):
    client = client_for(tmp_path)
    task_id = "00000012-0000-4000-8000-000000000012"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder("2026-10-16T11:00:00+08:00")))

    response = client.post(f"/api/v1/reminders/{task_id}/acknowledgment", json=body)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_request"


def test_ack_non_object_body_is_400(tmp_path: Path):
    client = client_for(tmp_path)
    task_id = "00000013-0000-4000-8000-000000000013"
    seed(tmp_path, task_payload(task_id, reminder=NONE_REMINDER))

    response = client.post(f"/api/v1/reminders/{task_id}/acknowledgment", json=["x"])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------- 锁与写失败

def test_ack_write_failure_does_not_change_memory(tmp_path: Path, monkeypatch):
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "00000014-0000-4000-8000-000000000014"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(session["startedAt"])))
    before = stored_task(tmp_path, task_id)

    import app.modules.tasks.storage.state_store as state_store

    def _boom(*args, **kwargs):
        raise OSError("注入写失败")

    monkeypatch.setattr(state_store.os, "replace", _boom)

    response = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "storage_write_failed"
    monkeypatch.undo()
    # 内存与磁盘都未提前变为 acknowledged
    assert stored_task(tmp_path, task_id) == before


def test_session_creation_failure_keeps_previous_session(tmp_path: Path, monkeypatch):
    """T16 项③适配：仅在「确有过期项需提交」时注入写失败才应 500。

    无过期项时 commit 走 skip 短路（不写盘），故不会触发写失败。
    """
    client = client_for(tmp_path)
    first = open_session(client)

    # 种一条已过期的 scheduled 提醒 → 新会话创建时必须提交过期状态
    seed_stale_scheduled(tmp_path)

    import app.modules.tasks.storage.state_store as state_store

    def _boom(*args, **kwargs):
        raise OSError("注入写失败")

    monkeypatch.setattr(state_store.os, "replace", _boom)

    failed = client.post("/api/v1/reminder-sessions")
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "storage_write_failed"

    monkeypatch.undo()
    # 旧会话仍然有效
    due = client.get(f"/api/v1/reminder-sessions/{first['sessionId']}/due")
    assert due.status_code == 200


def test_session_creation_without_expiry_skips_write(tmp_path: Path, monkeypatch):
    """T16 项③：无过期项时会话创建不产生写盘与 .bak 轮换。"""
    client = client_for(tmp_path)
    first = open_session(client)
    assert not (tmp_path / "state.json").exists()

    import app.modules.tasks.storage.state_store as state_store

    calls = {"replace": 0}
    real_replace = state_store.os.replace

    def _count(*args, **kwargs):
        calls["replace"] += 1
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(state_store.os, "replace", _count)

    second = client.post("/api/v1/reminder-sessions")
    assert second.status_code == 200
    # 跳过写盘：无 tmp/主文件写入，也无 .bak
    assert calls["replace"] == 0
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "state.json.bak").exists()
    assert second.json()["sessionId"] != first["sessionId"]

    monkeypatch.undo()
    # 新会话仍可正常 due
    due = client.get(f"/api/v1/reminder-sessions/{second.json()['sessionId']}/due")
    assert due.status_code == 200


# ---------------------------------------------------------------- §6 生命周期

def test_lifecycle_completion_cancels_pending_and_new_session_does_not_revive(
    tmp_path: Path,
):
    """§6：完成使未触发的 scheduled 变 cancelled（换版本）；新会话不复活终态。"""
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "00000015-0000-4000-8000-000000000015"
    started_dt = datetime.fromisoformat(session["startedAt"])
    due_time = (started_dt + timedelta(minutes=10)).isoformat()
    seed(
        tmp_path,
        task_payload(
            task_id,
            due=resolved_due(due_time),
            reminder={
                "mode": "relative",
                "requestedAt": None,
                "scheduledAt": (started_dt - timedelta(minutes=20)).isoformat(),
                "relativeTo": "due",
                "offsetMinutes": 30,
                "state": "scheduled",
                "acknowledgedAt": None,
                "revision": VERSION,
            },
        ),
    )

    patched = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "completed"})
    assert patched.status_code == 200
    reminder = patched.json()["task"]["reminder"]
    assert reminder["state"] == "cancelled"
    new_version = reminder["revision"]
    assert new_version != VERSION

    # 旧版本确认 → 409 version_conflict（第 2 步）
    old = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )
    assert old.status_code == 409
    assert old.json()["error"]["code"] == "reminder_version_conflict"

    # 重新打开不恢复提醒
    reopened = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "open"})
    assert reopened.status_code == 200
    assert reopened.json()["task"]["reminder"]["state"] == "cancelled"
    assert reopened.json()["task"]["reminder"]["revision"] == new_version

    # 新会话的过期扫描不复活 cancelled（scheduledAt 为 null）
    second = open_session(client)
    due = client.get(f"/api/v1/reminder-sessions/{second['sessionId']}/due")
    assert due.json()["reminders"] == []
    assert stored_task(tmp_path, task_id)["reminder"]["state"] == "cancelled"


def test_lifecycle_time_change_does_not_restart_terminal_reminder(tmp_path: Path):
    """§6：改任务时间不重启 acknowledged 终态，版本保持不变。"""
    client = client_for(tmp_path)
    task_id = "00000016-0000-4000-8000-000000000016"
    acked_at = "2026-10-16T09:00:00+08:00"
    seed(
        tmp_path,
        task_payload(
            task_id,
            due=resolved_due("2026-10-20T10:00:00+08:00"),
            reminder={
                "mode": "relative",
                "requestedAt": None,
                "scheduledAt": "2026-10-20T09:30:00+08:00",
                "relativeTo": "due",
                "offsetMinutes": 30,
                "state": "acknowledged",
                "acknowledgedAt": acked_at,
                "revision": VERSION,
            },
        ),
    )

    patched = client.patch(f"/api/v1/tasks/{task_id}", json={"dueTime": None})

    assert patched.status_code == 200
    reminder = patched.json()["task"]["reminder"]
    assert reminder["state"] == "acknowledged"
    assert reminder["revision"] == VERSION
    assert reminder["acknowledgedAt"] == acked_at
    assert reminder["scheduledAt"] == "2026-10-20T09:30:00+08:00"


def test_lifecycle_acknowledged_not_returned_in_due_after_refresh(tmp_path: Path):
    """§6：普通刷新后已确认提醒不进入 due，且同版本回放不重复写状态。"""
    client = client_for(tmp_path)
    session = open_session(client)
    task_id = "00000017-0000-4000-8000-000000000017"
    seed(tmp_path, task_payload(task_id, reminder=manual_reminder(session["startedAt"])))

    first = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )
    assert first.status_code == 200

    # 刷新 → 新会话；已确认项不进入新会话的 due
    refreshed = open_session(client)
    due = client.get(f"/api/v1/reminder-sessions/{refreshed['sessionId']}/due")
    assert due.json()["reminders"] == []

    # 旧会话 ID 的同版本确认仍回放（第 3 步），时间戳不变
    replay = client.post(
        f"/api/v1/reminders/{task_id}/acknowledgment",
        json={"sessionId": session["sessionId"], "reminderVersion": VERSION},
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()


def test_health_and_home_still_work(tmp_path: Path):
    client = client_for(tmp_path)

    assert client.get("/health").json() == {"status": "ok"}
    assert "Snap2Todo" in client.get("/").text
