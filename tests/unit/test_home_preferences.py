"""首页偏好（天气城市）持久化回归。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.home import preferences


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app, base_url="http://127.0.0.1:17843")


def headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/bootstrap").json()["token"]
    return {"X-Workbench-Token": token, "Origin": "http://127.0.0.1:17843"}


def test_defaults_to_nanjing(client):
    body = client.get("/api/v1/preferences", headers=headers(client)).json()
    assert body == {"city": "南京"}


def test_city_roundtrip_and_persist_across_restart(tmp_path):
    root = tmp_path / "data"
    app = create_app(root)
    client = TestClient(app, base_url="http://127.0.0.1:17843")
    h = headers(client)

    saved = client.put("/api/v1/preferences", headers={**h, "Content-Type": "application/json"}, json={"city": "成都"})
    assert saved.status_code == 200
    assert saved.json() == {"city": "成都"}

    again = create_app(root)
    second = TestClient(again, base_url="http://127.0.0.1:17843")
    assert second.get("/api/v1/preferences", headers=headers(second)).json() == {"city": "成都"}


@pytest.mark.parametrize(
    "payload",
    [{"city": ""}, {"city": "   "}, {"city": 123}, {}, {"city": "成都", "foo": 1}],
)
def test_invalid_city_rejected(client, payload):
    response = client.put(
        "/api/v1/preferences",
        headers={**headers(client), "Content-Type": "application/json"},
        json=payload,
    )
    assert response.status_code in (400, 422)


def test_preferences_requires_token(client):
    assert client.get("/api/v1/preferences").status_code == 403


def test_city_length_capped(tmp_path):
    payload = preferences.write_preferences(tmp_path, {"city": "长" * 40})
    assert len(payload["city"]) == preferences.MAX_CITY_LENGTH
