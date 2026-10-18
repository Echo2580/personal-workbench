"""全局搜索接口回归。"""

from __future__ import annotations

from pathlib import Path

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


def post_json(client, path, payload, h):
    return client.post(path, headers={**h, "Content-Type": "application/json"}, json=payload)


def test_search_requires_token(client: TestClient):
    assert client.get("/api/v1/search?q=x").status_code == 403


def test_empty_query_returns_empty_groups(client: TestClient):
    response = client.get("/api/v1/search", headers=headers(client))
    assert response.status_code == 200
    assert response.json() == {"query": "", "groups": [], "total": 0}


def test_search_too_long_rejected(client: TestClient):
    h = headers(client)
    assert client.get("/api/v1/search", params={"q": "长" * 51}, headers=h).status_code == 422


def test_search_finds_tasks_and_goals(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    h = headers(client)

    created = post_json(client, "/api/v1/tasks", {"title": "整理毕业设计材料"}, h)
    assert created.status_code == 201

    goal = post_json(
        client,
        "/api/v1/goals",
        {
            "kind": "plan",
            "title": "毕业设计冲刺计划",
            "description": "两周完成初稿",
            "startDate": "2026-10-18",
            "targetDate": "2026-11-01",
            "dailyCapacity": 2,
            "constraints": [],
            "recurrence": None,
        },
        h,
    )
    assert goal.status_code == 201

    result = client.get("/api/v1/search", params={"q": "毕业设计"}, headers=h)
    assert result.status_code == 200
    body = result.json()
    groups = {group["key"]: group for group in body["groups"]}
    assert set(groups) == {"tasks", "goals"}
    assert body["total"] == 2
    assert groups["tasks"]["items"][0]["title"] == "整理毕业设计材料"
    assert groups["tasks"]["items"][0]["route"] == "/tasks"
    assert groups["goals"]["items"][0]["title"] == "毕业设计冲刺计划"
    assert groups["goals"]["items"][0]["badge"] == "计划"


def test_search_finds_projects(tmp_path):
    root = tmp_path / "projects"
    project = root / "示例项目"
    project.mkdir(parents=True)
    (project / "main.py").write_text("print('hi')\n", encoding="utf-8")

    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    h = headers(client)

    manual = post_json(client, "/api/v1/projects/manual", {"path": str(project)}, h)
    assert manual.status_code == 200, manual.text

    result = client.get("/api/v1/search", params={"q": "示例项目"}, headers=h)
    assert result.status_code == 200
    groups = {group["key"]: group for group in result.json()["groups"]}
    assert "projects" in groups
    item = groups["projects"]["items"][0]
    assert item["title"] == "示例项目"
    assert item["route"] == "/projects"
