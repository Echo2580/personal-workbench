"""构造样本测试 T06 任务接口（CRUD + PATCH §4.2 + §7.1 S02—S06）。

所有数据均为接口测试的构造样本，不代表真实提取或保存结果。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tasks_test_app import create_app
from app.modules.tasks.storage import commit, load_snapshot


SOURCE_A = "11111111-1111-4111-8111-111111111111"
SOURCE_B = "22222222-2222-4222-8222-222222222222"
DRAFT_ID = "33333333-3333-4333-8333-333333333333"
VERSION = "55555555-5555-4555-8555-555555555555"
VERSION_2 = "66666666-6666-4666-8666-666666666666"
STAMP = "2026-10-20T08:00:00+08:00"
STAMP_LATER = "2026-10-21T08:00:00+08:00"
DUE_DATETIME = "2026-10-20T10:00:00+08:00"
DUE_DATE_ONLY = "2026-10-20"
PAST_STAMP = "2020-01-01T00:00:00+08:00"
FUTURE_STAMP = "2099-01-01T00:00:00+08:00"

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


def text_source(source_id: str = SOURCE_A, text: str = "请交报告") -> dict[str, Any]:
    return {
        "id": source_id,
        "kind": "text",
        "originalText": text,
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": ("a" if source_id == SOURCE_A else "b") * 64,
    }


def resolved_datetime(value: str, raw: str = "10月20日 10:00") -> dict[str, Any]:
    return {
        "rawExpression": raw,
        "precision": "datetime",
        "resolvedValue": value,
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def date_only(value: str = DUE_DATE_ONLY) -> dict[str, Any]:
    return {
        "rawExpression": "10月20日",
        "precision": "date",
        "resolvedValue": value,
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def waiting_time() -> dict[str, Any]:
    """领域形状（含 timeZone），用于种子数据。"""
    return {
        "rawExpression": "周五前",
        "precision": "relative",
        "resolvedValue": None,
        "timeZone": "Asia/Shanghai",
        "status": "needs_confirmation",
    }


def waiting_time_input() -> dict[str, Any]:
    """请求输入形状：timeZone 由服务端固定，客户端不得提交（§4.2）。"""
    return {
        "rawExpression": "周五前",
        "precision": "relative",
        "resolvedValue": None,
        "status": "needs_confirmation",
    }


def task_payload(
    task_id: str,
    *,
    source_id: str = SOURCE_A,
    title: str = "交报告",
    status: str = "open",
    created_at: str = STAMP,
    start_time: dict[str, Any] | None = None,
    due_time: dict[str, Any] | None = None,
    requirements: list[str] | None = None,
    applicability: dict[str, Any] | None = None,
    source_excerpt: str | None = "请交报告",
    reminder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "draftId": DRAFT_ID,
        "sourceId": source_id,
        "title": title,
        "startTime": start_time,
        "dueTime": due_time,
        "requirements": requirements if requirements is not None else [],
        "applicability": applicability
        if applicability is not None
        else {"text": None, "status": "not_stated"},
        "sourceExcerpt": source_excerpt,
        "reviewIssues": [],
        "status": status,
        "reminder": reminder if reminder is not None else deepcopy(NONE_REMINDER),
        "createdAt": created_at,
        "updatedAt": created_at,
    }


def scheduled_relative_reminder() -> dict[str, Any]:
    return {
        "mode": "relative",
        "requestedAt": None,
        "scheduledAt": "2026-10-20T09:30:00+08:00",
        "relativeTo": "due",
        "offsetMinutes": 30,
        "state": "scheduled",
        "acknowledgedAt": None,
        "revision": VERSION,
    }


def seed(root: Path, *tasks: dict[str, Any], sources: tuple[str, ...] = (SOURCE_A,)) -> None:
    def _mutate(snap):
        for sid in sources:
            snap = snap.add_source_meta(text_source(sid))
        for task in tasks:
            snap = snap.add_task(deepcopy(task))
        return snap

    result = commit(root, _mutate)
    assert result.error is None, result.error


TASK_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TASK_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TASK_3 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    return tmp_path


def make_client(data_root: Path) -> TestClient:
    return TestClient(create_app(data_root))


def test_list_defaults_to_open_and_filters(data_root: Path):
    seed(
        data_root,
        task_payload(TASK_1, status="open"),
        task_payload(TASK_2, status="completed"),
    )
    client = make_client(data_root)

    default = client.get("/api/v1/tasks")
    assert default.status_code == 200
    assert set(default.json()) == {"tasks"}
    assert [t["id"] for t in default.json()["tasks"]] == [TASK_1]

    completed = client.get("/api/v1/tasks", params={"status": "completed"})
    assert completed.status_code == 200
    assert [t["id"] for t in completed.json()["tasks"]] == [TASK_2]

    everything = client.get("/api/v1/tasks", params={"status": "all"})
    assert everything.status_code == 200
    assert {t["id"] for t in everything.json()["tasks"]} == {TASK_1, TASK_2}

    bad = client.get("/api/v1/tasks", params={"status": "pending"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_status"


def test_list_orders_by_created_at_desc_then_id_asc(data_root: Path):
    # 两个同刻任务 + 一个较晚任务
    seed(
        data_root,
        task_payload(TASK_1, created_at=STAMP),
        task_payload(TASK_2, created_at=STAMP),
        task_payload(TASK_3, created_at=STAMP_LATER),
    )
    client = make_client(data_root)

    ids = [t["id"] for t in client.get("/api/v1/tasks").json()["tasks"]]

    # 较晚的在前；同刻按 id 升序
    expected_same_moment = sorted([TASK_1, TASK_2])
    assert ids == [TASK_3, *expected_same_moment]


def test_task_detail_includes_source_metadata(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.get(f"/api/v1/tasks/{TASK_1}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"task", "source"}
    assert body["task"]["id"] == TASK_1
    assert set(body["source"]) == {
        "id",
        "kind",
        "mimeType",
        "fileName",
        "messageDate",
        "importedAt",
        "contentSha256",
    }
    assert "relativePath" not in body["source"]
    assert "originalText" not in body["source"]


def test_task_detail_not_found(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.get("/api/v1/tasks/99999999-9999-4999-8999-999999999999")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "task_not_found"
    assert body["error"]["details"] == {}


# ---------------------------------------------------------------- PATCH §7.1

def test_s02_title_only_keeps_everything_else(data_root: Path):
    """S02：只改 title → 200；dueTime 保持；revision 不变。"""
    seed(
        data_root,
        task_payload(
            TASK_1,
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=scheduled_relative_reminder(),
        ),
    )
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"title": "修改后的标题"})

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["title"] == "修改后的标题"
    assert task["dueTime"]["resolvedValue"] == DUE_DATETIME
    assert task["reminder"]["revision"] == VERSION
    assert task["reminder"]["state"] == "scheduled"
    assert task["reminder"]["scheduledAt"] == "2026-10-20T09:30:00+08:00"
    # updatedAt 刷新，createdAt 不变
    assert task["createdAt"] == STAMP
    assert task["updatedAt"] != STAMP


def test_s03_relative_reminder_becomes_blocked(data_root: Path):
    """S03：原 scheduled + PATCH dueTime=null → revision 更换、变 blocked。"""
    seed(
        data_root,
        task_payload(
            TASK_1,
            start_time=resolved_datetime("2026-10-20T08:00:00+08:00"),
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=scheduled_relative_reminder(),
        ),
    )
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"dueTime": None})

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["dueTime"] is None
    # 开始时间保留
    assert task["startTime"]["resolvedValue"] == "2026-10-20T08:00:00+08:00"
    reminder = task["reminder"]
    assert reminder["state"] == "blocked"
    assert reminder["scheduledAt"] is None
    # 用户配置保留
    assert reminder["relativeTo"] == "due"
    assert reminder["offsetMinutes"] == 30
    assert reminder["acknowledgedAt"] is None
    # 版本更换
    assert reminder["revision"] != VERSION


def test_s03_manual_requested_at_not_rewritten(data_root: Path):
    """S03：manual requestedAt 不被任务时间变化静默改写。"""
    manual = {
        "mode": "manual",
        "requestedAt": FUTURE_STAMP,
        "scheduledAt": FUTURE_STAMP,
        "relativeTo": None,
        "offsetMinutes": None,
        "state": "scheduled",
        "acknowledgedAt": None,
        "revision": VERSION,
    }
    seed(
        data_root,
        task_payload(
            TASK_1,
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=manual,
        ),
    )
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"dueTime": None})

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["requestedAt"] == FUTURE_STAMP
    assert reminder["scheduledAt"] == FUTURE_STAMP
    assert reminder["state"] == "scheduled"
    assert reminder["revision"] != VERSION


def test_s03_terminal_reminder_keeps_version_and_state(data_root: Path):
    """S03：原提醒为终态则保留版本/状态，不因改时间重算。"""
    acknowledged = {
        "mode": "relative",
        "requestedAt": None,
        "scheduledAt": "2026-10-20T09:30:00+08:00",
        "relativeTo": "due",
        "offsetMinutes": 30,
        "state": "acknowledged",
        "acknowledgedAt": STAMP,
        "revision": VERSION,
    }
    seed(
        data_root,
        task_payload(
            TASK_1,
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=acknowledged,
        ),
    )
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"dueTime": None})

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "acknowledged"
    assert reminder["scheduledAt"] == "2026-10-20T09:30:00+08:00"
    assert reminder["acknowledgedAt"] == STAMP
    assert reminder["revision"] == VERSION


@pytest.mark.parametrize(
    "body,field",
    [
        ({"title": None}, "title"),
        ({"requirements": None}, "requirements"),
        ({"reminder": None}, "reminder"),
        ({"status": None}, "status"),
        ({"applicability": None}, "applicability"),
    ],
)
def test_s04_null_not_allowed(data_root: Path, body: dict, field: str):
    """S04：非法 null → 422 task_validation_failed，路径指向字段，整体不修改。"""
    seed(data_root, task_payload(TASK_1, due_time=resolved_datetime(DUE_DATETIME)))
    client = make_client(data_root)
    before = load_snapshot(data_root).snapshot.tasks[TASK_1].model_dump(
        mode="json", by_alias=True
    )

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "task_validation_failed"
    paths = [fe["field"] for fe in error["details"]["fieldErrors"]]
    assert field in paths
    after = load_snapshot(data_root).snapshot.tasks[TASK_1].model_dump(
        mode="json", by_alias=True
    )
    assert after == before


@pytest.mark.parametrize(
    "body,expected_prefix",
    [
        ({"reminder": {"mode": "none"}}, "reminder"),
        (
            {
                "dueTime": {
                    "rawExpression": "周五前",
                    "precision": "relative",
                    "resolvedValue": None,
                }
            },
            "dueTime",
        ),
        ({"applicability": {"status": "not_stated"}}, "applicability"),
    ],
)
def test_s05_incomplete_objects_are_422(
    data_root: Path, body: dict, expected_prefix: str
):
    """S05：不完整嵌套对象 → 422，指出缺键，不做旧值合并。"""
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "task_validation_failed"
    paths = [fe["field"] for fe in error["details"]["fieldErrors"]]
    assert any(path.startswith(expected_prefix) for path in paths), paths
    # 整体不修改
    assert load_snapshot(data_root).snapshot.tasks[TASK_1].reminder.revision == VERSION


def test_s06_full_none_reminder_clears_configuration(data_root: Path):
    """S06：完整 mode=none 四键 → 200，state=not_set，新 revision。"""
    seed(
        data_root,
        task_payload(
            TASK_1,
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=scheduled_relative_reminder(),
        ),
    )
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "none",
                "requestedAt": None,
                "relativeTo": None,
                "offsetMinutes": None,
            }
        },
    )

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["mode"] == "none"
    assert reminder["state"] == "not_set"
    assert reminder["scheduledAt"] is None
    assert reminder["acknowledgedAt"] is None
    assert reminder["requestedAt"] is None
    assert reminder["relativeTo"] is None
    assert reminder["offsetMinutes"] is None
    assert reminder["revision"] != VERSION


@pytest.mark.parametrize(
    "extra",
    [
        {"state": "not_set"},
        {"revision": VERSION_2},
        {"scheduledAt": None},
        {"acknowledgedAt": None},
    ],
)
def test_s06_read_only_reminder_keys_are_400(data_root: Path, extra: dict):
    """S06：客户端提交只读键 → 400 invalid_request。"""
    seed(
        data_root,
        task_payload(
            TASK_1,
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=scheduled_relative_reminder(),
        ),
    )
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "none",
                "requestedAt": None,
                "relativeTo": None,
                "offsetMinutes": None,
                **extra,
            }
        },
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    paths = [fe["field"] for fe in error["details"]["fieldErrors"]]
    assert any(path.startswith("reminder") for path in paths), paths
    # 未修改
    assert load_snapshot(data_root).snapshot.tasks[TASK_1].reminder.revision == VERSION


# ---------------------------------------------------------------- 其他 PATCH 语义

def test_patch_task_not_found(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(
        "/api/v1/tasks/99999999-9999-4999-8999-999999999999", json={"title": "x"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"


@pytest.mark.parametrize("body", [{}, ["x"], "text", 5])
def test_patch_invalid_body_shape_is_400(data_root: Path, body):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_patch_unknown_and_read_only_top_level_keys_are_400(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    for field in ("id", "sourceId", "reviewIssues", "createdAt", "updatedAt", "unknown"):
        response = client.patch(f"/api/v1/tasks/{TASK_1}", json={field: "x"})
        assert response.status_code == 400, field
        error = response.json()["error"]
        assert error["code"] == "invalid_request"
        paths = [fe["field"] for fe in error["details"]["fieldErrors"]]
        assert field in paths, (field, paths)


def test_patch_manual_reminder_in_the_past_is_422(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "manual",
                "requestedAt": PAST_STAMP,
                "relativeTo": None,
                "offsetMinutes": None,
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "reminder_time_in_past"
    assert load_snapshot(data_root).snapshot.tasks[TASK_1].reminder.revision == VERSION


def test_patch_manual_reminder_in_the_future_succeeds(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "manual",
                "requestedAt": FUTURE_STAMP,
                "relativeTo": None,
                "offsetMinutes": None,
            }
        },
    )

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "scheduled"
    assert reminder["scheduledAt"] == FUTURE_STAMP
    assert reminder["requestedAt"] == FUTURE_STAMP


def test_patch_manual_reminder_blocked_when_time_needs_confirmation(
    data_root: Path,
):
    seed(data_root, task_payload(TASK_1, due_time=waiting_time()))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "manual",
                "requestedAt": FUTURE_STAMP,
                "relativeTo": None,
                "offsetMinutes": None,
            }
        },
    )

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "blocked"
    assert reminder["scheduledAt"] is None
    # 用户配置保留
    assert reminder["requestedAt"] == FUTURE_STAMP


def test_patch_relative_reminder_schedules_from_resolved_base(data_root: Path):
    seed(data_root, task_payload(TASK_1, due_time=resolved_datetime(DUE_DATETIME)))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "relative",
                "requestedAt": None,
                "relativeTo": "due",
                "offsetMinutes": 30,
            }
        },
    )

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "scheduled"
    assert reminder["scheduledAt"] == "2026-10-20T09:30:00+08:00"


def test_patch_relative_reminder_with_date_only_base_is_blocked(data_root: Path):
    seed(data_root, task_payload(TASK_1, due_time=date_only()))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "reminder": {
                "mode": "relative",
                "requestedAt": None,
                "relativeTo": "due",
                "offsetMinutes": 30,
            }
        },
    )

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "blocked"
    assert reminder["scheduledAt"] is None


def test_patch_completing_task_cancels_pending_reminder(data_root: Path):
    seed(
        data_root,
        task_payload(
            TASK_1,
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=scheduled_relative_reminder(),
        ),
    )
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"status": "completed"})

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["status"] == "completed"
    reminder = task["reminder"]
    assert reminder["state"] == "cancelled"
    assert reminder["scheduledAt"] is None
    assert reminder["revision"] != VERSION


def test_patch_reopening_task_does_not_restart_reminder(data_root: Path):
    cancelled = {
        "mode": "relative",
        "requestedAt": None,
        "scheduledAt": None,
        "relativeTo": "due",
        "offsetMinutes": 30,
        "state": "cancelled",
        "acknowledgedAt": None,
        "revision": VERSION,
    }
    seed(
        data_root,
        task_payload(
            TASK_1,
            status="completed",
            due_time=resolved_datetime(DUE_DATETIME),
            reminder=cancelled,
        ),
    )
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"status": "open"})

    assert response.status_code == 200
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "cancelled"
    assert reminder["revision"] == VERSION


def test_patch_recomputes_review_issues(data_root: Path):
    seed(data_root, task_payload(TASK_1, source_excerpt="请交报告"))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "dueTime": waiting_time_input(),
            "applicability": {"text": "仅本班同学", "status": "needs_confirmation"},
            "sourceExcerpt": None,
        },
    )

    assert response.status_code == 200
    codes = [i["code"] for i in response.json()["task"]["reviewIssues"]]
    assert codes == [
        "time_needs_confirmation",
        "applicability_needs_confirmation",
        "source_excerpt_missing",
    ]


def test_patch_requirements_and_excerpt_replacement(data_root: Path):
    seed(data_root, task_payload(TASK_1, requirements=[]))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={"requirements": ["带学生证"], "sourceExcerpt": " 保留空白 "},
    )

    assert response.status_code == 200
    task = response.json()["task"]
    assert task["requirements"] == ["带学生证"]
    assert task["sourceExcerpt"] == " 保留空白 "


def test_patch_invalid_time_zone_is_400(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(
        f"/api/v1/tasks/{TASK_1}",
        json={
            "dueTime": {
                "rawExpression": "10月20日",
                "precision": "datetime",
                "resolvedValue": DUE_DATETIME,
                "status": "resolved",
                "timeZone": "UTC",
            }
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_patch_blank_title_is_422(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    response = client.patch(f"/api/v1/tasks/{TASK_1}", json={"title": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "task_validation_failed"


# ---------------------------------------------------------------- DELETE

def test_delete_is_idempotent_and_keeps_source(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    first = client.delete(f"/api/v1/tasks/{TASK_1}")
    assert first.status_code == 204

    second = client.delete(f"/api/v1/tasks/{TASK_1}")
    assert second.status_code == 204

    assert client.get(f"/api/v1/tasks/{TASK_1}").status_code == 404
    # 来源不随任务删除
    assert client.get(f"/api/v1/sources/{SOURCE_A}").status_code == 200


def test_delete_does_not_affect_other_tasks_sharing_source(data_root: Path):
    seed(
        data_root,
        task_payload(TASK_1),
        task_payload(TASK_2),
    )
    client = make_client(data_root)

    assert client.delete(f"/api/v1/tasks/{TASK_1}").status_code == 204

    assert client.get(f"/api/v1/tasks/{TASK_2}").status_code == 200
    assert client.get(f"/api/v1/sources/{SOURCE_A}").status_code == 200


# ---------------------------------------------------------------- 持久化

def test_patch_and_delete_persist_across_new_app_instance(data_root: Path):
    seed(data_root, task_payload(TASK_1), task_payload(TASK_2))
    client = make_client(data_root)

    assert (
        client.patch(f"/api/v1/tasks/{TASK_1}", json={"title": "改过的标题"}).status_code
        == 200
    )
    assert client.delete(f"/api/v1/tasks/{TASK_2}").status_code == 204

    # 新实例（模拟重启）重读
    fresh = make_client(data_root)
    detail = fresh.get(f"/api/v1/tasks/{TASK_1}")
    assert detail.status_code == 200
    assert detail.json()["task"]["title"] == "改过的标题"
    assert fresh.get(f"/api/v1/tasks/{TASK_2}").status_code == 404

    snapshot = load_snapshot(data_root).snapshot
    assert set(snapshot.tasks) == {TASK_1}


def test_delete_writes_through_storage_component(data_root: Path):
    seed(data_root, task_payload(TASK_1))
    client = make_client(data_root)

    assert client.delete(f"/api/v1/tasks/{TASK_1}").status_code == 204

    payload = json.loads((data_root / "state.json").read_text(encoding="utf-8"))
    assert payload["tasks"] == {}
    # 来源仍在文件里
    assert SOURCE_A in payload["sources"]
