"""首页偏好（天气城市 + 自定义快速入口）持久化回归。"""

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


def put_preferences(client, payload):
    return client.put(
        "/api/v1/preferences",
        headers={**headers(client), "Content-Type": "application/json"},
        json=payload,
    )


def test_defaults(client):
    body = client.get("/api/v1/preferences", headers=headers(client)).json()
    assert body["city"] == "南京"
    assert body["quickEntries"] == []


def test_city_roundtrip_and_persist_across_restart(tmp_path):
    root = tmp_path / "data"
    app = create_app(root)
    client = TestClient(app, base_url="http://127.0.0.1:17843")

    saved = put_preferences(client, {"city": "成都"})
    assert saved.status_code == 200
    assert saved.json()["city"] == "成都"

    again = create_app(root)
    second = TestClient(again, base_url="http://127.0.0.1:17843")
    assert second.get("/api/v1/preferences", headers=headers(second)).json()["city"] == "成都"


def test_quick_entries_add_update_and_persist(tmp_path):
    root = tmp_path / "data"
    app = create_app(root)
    client = TestClient(app, base_url="http://127.0.0.1:17843")

    saved = put_preferences(
        client,
        {"quickEntries": [{"label": "Google", "url": "https://google.com"}, {"label": "B站", "url": "https://bilibili.com"}]},
    )
    assert saved.status_code == 200
    entries = saved.json()["quickEntries"]
    assert [entry["label"] for entry in entries] == ["Google", "B站"]
    assert all(entry["id"] for entry in entries)
    # 城市未传时保持不变
    assert saved.json()["city"] == "南京"

    # 部分更新：只改城市，不影响入口
    put_preferences(client, {"city": "杭州"})
    again = create_app(root)
    second = TestClient(again, base_url="http://127.0.0.1:17843")
    body = second.get("/api/v1/preferences", headers=headers(second)).json()
    assert body["city"] == "杭州"
    assert [entry["label"] for entry in body["quickEntries"]] == ["Google", "B站"]


def test_quick_entries_validation(client):
    assert put_preferences(client, {"quickEntries": "x"}).status_code == 422
    assert put_preferences(client, {"quickEntries": [{"label": "", "url": "https://a.com"}]}).status_code == 422
    assert put_preferences(client, {"quickEntries": [{"label": "A", "url": "ftp://a.com"}]}).status_code == 422
    assert put_preferences(client, {"quickEntries": [{"label": "A", "url": "https://a.com"}] * 9}).status_code == 422


@pytest.mark.parametrize("payload", [{"city": ""}, {"city": "   "}, {"city": 123}, {}, {"city": "成都", "foo": 1}])
def test_invalid_city_rejected(client, payload):
    assert put_preferences(client, payload).status_code in (400, 422)


def test_preferences_requires_token(client):
    assert client.get("/api/v1/preferences").status_code == 403


def test_city_length_capped(tmp_path):
    payload = preferences.write_preferences(tmp_path, {"city": "长" * 40})
    assert len(payload["city"]) == preferences.MAX_CITY_LENGTH
