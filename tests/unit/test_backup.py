"""数据备份：导出 / 恢复 / 概览接口回归。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app, base_url="http://127.0.0.1:17843")


def headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/bootstrap").json()["token"]
    return {"X-Workbench-Token": token, "Origin": "http://127.0.0.1:17843"}


def json_headers(client: TestClient) -> dict[str, str]:
    return {**headers(client), "Content-Type": "application/json"}


def seed_data(client: TestClient) -> None:
    h = json_headers(client)
    assert client.post("/api/v1/tasks", headers=h, json={"title": "备份测试任务"}).status_code in (200, 201)
    assert client.post("/api/v1/notes", headers=h, json={"text": "备份测试笔记"}).status_code == 201
    assert client.put("/api/v1/preferences", headers=h, json={"city": "成都"}).status_code == 200
    goal = client.post(
        "/api/v1/goals",
        headers=h,
        json={
            "kind": "plan",
            "title": "备份测试目标",
            "description": None,
            "startDate": "2026-10-18",
            "targetDate": "2026-11-01",
            "dailyCapacity": 1,
            "constraints": [],
            "recurrence": None,
        },
    )
    assert goal.status_code == 201


def export_bundle(client: TestClient) -> dict:
    response = client.get("/api/v1/backup/export", headers=headers(client))
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    return response.json()


def test_backup_requires_token(client):
    assert client.get("/api/v1/backup/export").status_code == 403
    assert client.get("/api/v1/backup/info").status_code == 403
    assert client.post("/api/v1/backup/restore").status_code == 403


def test_export_contains_expected_sections(client):
    seed_data(client)
    bundle = export_bundle(client)
    assert bundle["format"] == "personal-workbench-backup"
    assert bundle["formatVersion"] == 1
    assert bundle["appVersion"]
    data = bundle["data"]
    for key in ("tasksState", "home", "settingsToml", "projectsToml", "history"):
        assert key in data
    assert data["tasksState"]["schemaVersion"] >= 1
    assert data["home"]["notes"]["items"][0]["text"] == "备份测试笔记"
    assert data["home"]["preferences"]["city"] == "成都"
    assert "<" not in json.dumps(data["projectsToml"])  # TOML 文本，不是 HTML


def test_info_lists_counts_and_backups(client):
    seed_data(client)
    info = client.get("/api/v1/backup/info", headers=headers(client)).json()
    assert info["summary"]["tasks"] >= 1
    assert info["summary"]["notes"] == 1
    assert info["summary"]["goals"] >= 1
    assert info["summary"]["projects"] == 0
    assert info["dataDir"].endswith("data")
    assert info["backups"] == []


def test_restore_roundtrip(client, tmp_path):
    seed_data(client)
    before = export_bundle(client)

    # 制造额外数据并改动偏好
    h = json_headers(client)
    assert client.post("/api/v1/tasks", headers=h, json={"title": "之后新增的任务"}).status_code in (200, 201)
    assert client.put("/api/v1/preferences", headers=h, json={"city": "南京"}).status_code == 200

    restore = client.post("/api/v1/backup/restore", headers=h, content=json.dumps(before).encode("utf-8"))
    assert restore.status_code == 200, restore.text
    body = restore.json()
    assert body["restored"] is True
    assert body["autoBackup"].startswith("auto-")

    tasks = client.get("/api/v1/tasks?status=all", headers=headers(client)).json()["tasks"]
    assert [task["title"] for task in tasks] == ["备份测试任务"]
    notes = client.get("/api/v1/notes", headers=headers(client)).json()["items"]
    assert [note["text"] for note in notes] == ["备份测试笔记"]
    assert client.get("/api/v1/preferences", headers=headers(client)).json()["city"] == "成都"

    info = client.get("/api/v1/backup/info", headers=headers(client)).json()
    assert len(info["backups"]) == 1
    assert info["backups"][0]["name"].startswith("auto-")


def test_restore_rejects_invalid_payloads(client):
    h = json_headers(client)
    cases = [
        (b"", 400),
        (b"not-json", 400),
        (json.dumps({"format": "other"}).encode(), 400),
        (json.dumps({"format": "personal-workbench-backup", "formatVersion": 99, "data": {}}).encode(), 400),
        (json.dumps({"format": "personal-workbench-backup", "formatVersion": 1, "data": {"tasksState": {"schemaVersion": 1}}}).encode(), 422),
        (
            json.dumps(
                {
                    "format": "personal-workbench-backup",
                    "formatVersion": 1,
                    "data": {"settingsToml": "[broken"},
                }
            ).encode(),
            400,
        ),
    ]
    for payload, expected in cases:
        response = client.post("/api/v1/backup/restore", headers=h, content=payload)
        assert response.status_code == expected, (payload[:60], response.status_code, response.text)


def test_restore_keeps_old_data_when_validation_fails(client):
    seed_data(client)
    before = client.get("/api/v1/tasks?status=all", headers=headers(client)).json()["tasks"]
    bad = json.dumps(
        {"format": "personal-workbench-backup", "formatVersion": 1, "data": {"tasksState": {"bad": 1}}}
    ).encode()
    response = client.post("/api/v1/backup/restore", headers=json_headers(client), content=bad)
    assert response.status_code == 422
    after = client.get("/api/v1/tasks?status=all", headers=headers(client)).json()["tasks"]
    assert [task["title"] for task in after] == [task["title"] for task in before]
