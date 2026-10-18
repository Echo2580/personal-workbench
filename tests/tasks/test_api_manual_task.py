"""手动新建待办（POST /api/v1/tasks）的接口回归。"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.modules.tasks.app_factory import create_tasks_app

DUE = {
    "rawExpression": "明天 18:00",
    "precision": "datetime",
    "resolvedValue": "2099-10-19T18:00:00+08:00",
    "status": "resolved",
}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_tasks_app(tmp_path / "data"))


def create(client: TestClient, **overrides):
    payload = {"title": "手动建一条待办", **overrides}
    return client.post("/api/v1/tasks", json=payload)


def test_manual_task_created_with_manual_source(client: TestClient):
    response = create(
        client,
        dueTime=DUE,
        requirements=["带材料", "  "],
        note="周五前把材料交到办公室",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    task = body["task"]
    assert task["title"] == "手动建一条待办"
    assert task["status"] == "open"
    assert task["requirements"] == ["带材料"]  # 空白项被丢弃
    assert task["sourceExcerpt"] == "周五前把材料交到办公室"
    # 手动任务由本人创建：不应带任何"待确认"问题
    assert task["reviewIssues"] == []
    assert body["source"]["kind"] == "manual"
    assert body["source"]["originalText"] == "周五前把材料交到办公室"

    listing = client.get("/api/v1/tasks?status=all").json()
    assert [item["id"] for item in listing["tasks"]] == [task["id"]]

    detail = client.get(f"/api/v1/tasks/{task['id']}")
    assert detail.status_code == 200
    assert detail.json()["task"]["sourceId"] == body["source"]["id"]


def test_manual_task_is_persisted_across_restart(tmp_path):
    root = tmp_path / "data"
    first = TestClient(create_tasks_app(root))
    created = create(first, dueTime=DUE).json()
    second = TestClient(create_tasks_app(root))
    listing = second.get("/api/v1/tasks?status=all").json()
    assert [item["id"] for item in listing["tasks"]] == [created["task"]["id"]]
    # 来源按契约只暴露七键元数据（不含 originalText），但 kind 必须保留 manual
    source = second.get(f"/api/v1/sources/{created['source']['id']}")
    assert source.status_code == 200
    assert source.json()["source"]["kind"] == "manual"
    content = second.get(f"/api/v1/sources/{created['source']['id']}/content")
    assert content.status_code == 200
    assert content.text == "手动建一条待办"


def test_manual_task_rejects_blank_title(client: TestClient):
    assert create(client, title="   ").status_code == 422
    assert create(client, title="").status_code == 422


def test_manual_task_rejects_unknown_field(client: TestClient):
    assert create(client, priority="高").status_code == 400


def test_manual_task_relative_reminder_is_scheduled(client: TestClient):
    body = create(
        client,
        dueTime=DUE,
        reminder={"mode": "relative", "requestedAt": None, "relativeTo": "due", "offsetMinutes": 30},
    ).json()
    reminder = body["task"]["reminder"]
    assert reminder["state"] == "scheduled"
    assert reminder["scheduledAt"].startswith("2099-10-19T17:30")


def test_manual_task_past_manual_reminder_rejected(client: TestClient):
    payload = {
        "mode": "manual",
        "requestedAt": "2020-01-01T00:00:00+08:00",
        "relativeTo": None,
        "offsetMinutes": None,
    }
    assert create(client, reminder=copy.deepcopy(payload)).status_code == 422


def test_manual_task_completed_filter_excludes_it(client: TestClient):
    created = create(client).json()
    assert client.get("/api/v1/tasks?status=open").json()["tasks"]
    client.patch(f"/api/v1/tasks/{created['task']['id']}", json={"status": "completed"})
    assert client.get("/api/v1/tasks?status=open").json()["tasks"] == []
    assert len(client.get("/api/v1/tasks?status=completed").json()["tasks"]) == 1
