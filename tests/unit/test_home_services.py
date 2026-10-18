"""首页数据服务（天气/随手记）的接口回归。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.home import services


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app, base_url="http://127.0.0.1:17843")


def headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/bootstrap").json()["token"]
    return {"X-Workbench-Token": token, "Origin": "http://127.0.0.1:17843"}


def test_home_module_is_registered_without_nav_route(client: TestClient):
    modules = {m["id"]: m for m in client.get("/api/v1/bootstrap").json()["modules"]}
    assert modules["home"]["status"] == "available"
    assert modules["home"]["route"] is None


def test_weather_returns_normalised_payload(client: TestClient, monkeypatch):
    def fake_fetch(city):
        return {
            "city": city,
            "temperature": 24,
            "condition": "多云",
            "high": 27,
            "low": 19,
            "humidity": 61,
            "wind": 8.5,
            "forecast": [{"time": "16:00", "temperature": 25}],
            "fetchedAt": "2026-10-18T15:00:00+08:00",
            "cached": False,
        }

    monkeypatch.setattr(services, "fetch_weather", fake_fetch)
    response = client.get("/api/v1/weather?city=杭州", headers=headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["city"] == "杭州"
    assert body["condition"] == "多云"
    assert body["humidity"] == 61


def test_weather_failure_maps_to_503(client: TestClient, monkeypatch):
    def boom(city):
        raise services.HomeServiceError("weather_unavailable", "天气服务暂时不可用。", 503)

    monkeypatch.setattr(services, "fetch_weather", boom)
    response = client.get("/api/v1/weather?city=南京", headers=headers(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "weather_unavailable"


def test_notes_initial_empty(client: TestClient):
    assert client.get("/api/v1/notes", headers=headers(client)).json()["items"] == []


def test_notes_add_list_update_delete(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    h = headers(client)
    json_headers = {**h, "Content-Type": "application/json"}

    first = client.post("/api/v1/notes", headers=json_headers, json={"text": "先做完最重要的一件事"})
    assert first.status_code == 201
    note = first.json()["item"]
    assert note["text"] == "先做完最重要的一件事"
    assert note["id"] and note["createdAt"]

    second = client.post("/api/v1/notes", headers=json_headers, json={"text": "少一点切换"})
    assert second.status_code == 201

    items = client.get("/api/v1/notes", headers=h).json()["items"]
    assert [item["text"] for item in items] == ["少一点切换", "先做完最重要的一件事"]

    updated = client.put(
        f"/api/v1/notes/{note['id']}",
        headers=json_headers,
        json={"text": "先做完最重要的一件事（改）"},
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["text"] == "先做完最重要的一件事（改）"

    deleted = client.delete(f"/api/v1/notes/{note['id']}", headers=h)
    assert deleted.status_code == 204
    remaining = client.get("/api/v1/notes", headers=h).json()["items"]
    assert [item["text"] for item in remaining] == ["少一点切换"]

    disk = json.loads((tmp_path / "data" / "home" / "notes.json").read_text(encoding="utf-8"))
    assert [item["text"] for item in disk["items"]] == ["少一点切换"]


def test_notes_validation(client: TestClient):
    h = headers(client)
    json_headers = {**h, "Content-Type": "application/json"}
    assert client.post("/api/v1/notes", headers=json_headers, json={}).status_code == 400
    assert client.post("/api/v1/notes", headers=json_headers, json={"text": ""}).status_code == 422
    assert client.post("/api/v1/notes", headers=json_headers, json={"text": "x", "foo": 1}).status_code == 400
    too_long = "长" * 501
    assert client.post("/api/v1/notes", headers=json_headers, json={"text": too_long}).status_code == 422
    assert client.delete("/api/v1/notes/not-exist", headers=h).status_code == 404


def test_notes_migrates_legacy_lines(tmp_path):
    data_dir = tmp_path / "data"
    path = data_dir / "home" / "notes.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"lines": ["旧笔记一", "旧笔记二"], "updatedAt": "2026-10-01T09:00:00+08:00"}, ensure_ascii=False),
        encoding="utf-8",
    )

    notes = services.read_notes(data_dir)
    assert [item["text"] for item in notes["items"]] == ["旧笔记一", "旧笔记二"]
    assert all(item["id"] for item in notes["items"])


def test_home_endpoints_require_token(client: TestClient):
    assert client.get("/api/v1/weather").status_code == 403
    assert client.get("/api/v1/notes").status_code == 403
    assert client.post("/api/v1/notes").status_code == 403
