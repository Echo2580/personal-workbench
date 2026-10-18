"""首页数据服务（天气/段子/随手记）的接口回归。"""

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


def test_home_module_is_registered_without_nav_route(client: TestClient):
    modules = {m["id"]: m for m in client.get("/api/v1/bootstrap").json()["modules"]}
    assert modules["home"]["status"] == "available"
    assert modules["home"]["route"] is None


def test_weather_returns_normalised_payload(client: TestClient, monkeypatch):
    from app.modules.home import services

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
    from app.modules.home import services

    def boom(city):
        raise services.HomeServiceError("weather_unavailable", "天气服务暂时不可用。", 503)

    monkeypatch.setattr(services, "fetch_weather", boom)
    response = client.get("/api/v1/weather?city=南京", headers=headers(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "weather_unavailable"


def test_notes_roundtrip_and_persist(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    h = headers(client)

    assert client.get("/api/v1/notes", headers=h).json()["lines"] == []

    saved = client.put(
        "/api/v1/notes",
        headers={**h, "Content-Type": "application/json"},
        json={"lines": ["先做完最重要的一件事", "  ", "少一点切换"]},
    )
    assert saved.status_code == 200
    assert saved.json()["lines"] == ["先做完最重要的一件事", "少一点切换"]

    reloaded = client.get("/api/v1/notes", headers=h).json()
    assert reloaded["lines"] == ["先做完最重要的一件事", "少一点切换"]

    disk = json.loads((tmp_path / "data" / "home" / "notes.json").read_text(encoding="utf-8"))
    assert disk["lines"] == ["先做完最重要的一件事", "少一点切换"]


def test_notes_validation(client: TestClient):
    h = headers(client)
    assert client.put("/api/v1/notes", headers={**h, "Content-Type": "application/json"},
                      json={"lines": "not-a-list"}).status_code == 400
    assert client.put("/api/v1/notes", headers={**h, "Content-Type": "application/json"},
                      json={"lines": [1, 2]}).status_code == 400
    assert client.put("/api/v1/notes", headers={**h, "Content-Type": "application/json"},
                      json={"lines": ["x"], "foo": 1}).status_code == 400
    too_long = "长" * 201
    assert client.put("/api/v1/notes", headers={**h, "Content-Type": "application/json"},
                      json={"lines": [too_long]}).status_code == 422


def test_home_endpoints_require_token(client: TestClient):
    assert client.get("/api/v1/weather").status_code == 403
    assert client.get("/api/v1/daily-joke").status_code == 403
    assert client.get("/api/v1/notes").status_code == 403
