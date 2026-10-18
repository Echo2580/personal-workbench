"""首页数据服务（天气/段子/随手记）的接口回归。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.home.joke_model import MockJokeModel
from app.modules.home.services import JokeModelError


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


def test_daily_joke_is_cached_per_day_and_refresh_forces_new(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    model = MockJokeModel(joke="第一天：办公室里最忙的人，是打印机。")
    app.state.joke_model = model

    first = client.get("/api/v1/daily-joke", headers=headers(client))
    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert "打印机" in first.json()["joke"]
    assert len(model.calls) == 1

    second = client.get("/api/v1/daily-joke", headers=headers(client))
    assert second.json()["cached"] is True
    assert len(model.calls) == 1  # 同一天命中缓存，不再调模型

    model.joke = "第二天：我的待办列表学会了自我繁殖。"
    refreshed = client.get("/api/v1/daily-joke?refresh=1", headers=headers(client))
    assert refreshed.status_code == 200
    assert "自我繁殖" in refreshed.json()["joke"]
    assert len(model.calls) == 2
    assert refreshed.json()["cached"] is False


def test_daily_joke_survives_restart(tmp_path):
    root = tmp_path / "data"
    first_app = create_app(root)
    first = TestClient(first_app, base_url="http://127.0.0.1:17843")
    first_app.state.joke_model = MockJokeModel(joke="重启也还在的段子。")
    assert first.get("/api/v1/daily-joke", headers=headers(first)).status_code == 200

    second_app = create_app(root)
    second = TestClient(second_app, base_url="http://127.0.0.1:17843")
    model = MockJokeModel(joke="不该被调用。")
    second_app.state.joke_model = model
    cached = second.get("/api/v1/daily-joke", headers=headers(second))
    assert cached.status_code == 200
    assert cached.json()["cached"] is True
    assert cached.json()["joke"] == "重启也还在的段子。"
    assert model.calls == []


def test_daily_joke_model_error_maps_to_503(tmp_path):
    app = create_app(tmp_path / "data")
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    app.state.joke_model = MockJokeModel(error=JokeModelError("未配置模型密钥，无法生成段子。"))
    response = client.get("/api/v1/daily-joke", headers=headers(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "joke_unavailable"


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
