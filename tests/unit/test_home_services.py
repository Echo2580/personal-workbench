"""首页数据服务（天气/随手记）的接口回归。"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.home import services


class _FakeGeocodeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeGeocodeClient:
    """按查询名返回预设地理编码结果，并记录实际查询顺序。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url, params=None):
        name = (params or {}).get("name", "")
        self.calls.append(name)
        payload = self.mapping.get(name)
        if isinstance(payload, Exception):
            raise payload
        return _FakeGeocodeResponse(payload or {})


def _geo_results(*entries):
    return {
        "results": [
            {
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "population": population,
                "country_code": "CN",
            }
            for name, latitude, longitude, population in entries
        ]
    }


def test_geocode_prefers_prefecture_city_over_homonymous_town():
    """「洛阳」原查询会先命中福建洛阳镇，加查「洛阳市」后应选河南洛阳。"""
    client = _FakeGeocodeClient(
        {
            "洛阳": _geo_results(("洛阳", 24.95938, 118.683, 66188)),
            "洛阳市": _geo_results(("洛阳市", 34.67345, 112.43684, 1390581)),
        }
    )

    latitude, longitude = services._geocode(client, "洛阳")

    assert (latitude, longitude) == pytest.approx((34.67345, 112.43684))
    assert client.calls == ["洛阳", "洛阳市"]


def test_geocode_uses_pinyin_fallback_when_chinese_index_misses_city():
    """「信阳」中文索引里只有山东同名村，拼音查询能找回河南信阳。"""
    client = _FakeGeocodeClient(
        {
            "信阳": _geo_results(("信阳", 35.633, 119.693, None)),
            "信阳市": {"results": []},
            "xinyang": _geo_results(("Xinyang", 32.123, 114.066, 1416800)),
        }
    )

    latitude, longitude = services._geocode(client, "信阳")

    assert (latitude, longitude) == pytest.approx((32.123, 114.066))
    assert client.calls == ["信阳", "信阳市", "xinyang"]


def test_geocode_keeps_direct_city_hit_without_extra_queries():
    client = _FakeGeocodeClient({"台州": _geo_results(("台州", 28.66, 121.43, 1485502))})

    latitude, longitude = services._geocode(client, "台州")

    assert (latitude, longitude) == pytest.approx((28.66, 121.43))
    # 查原名和「原名+市」两个候选即可命中，不再触发拼音兜底。
    assert client.calls == ["台州", "台州市"]


def test_geocode_english_name_uses_first_relevant_result():
    client = _FakeGeocodeClient(
        {
            "Luoyang": _geo_results(
                ("洛阳市", 34.67345, 112.43684, 1390581),
                ("Luoyang", 23.16244, 114.27342, 123144),
            )
        }
    )

    latitude, longitude = services._geocode(client, "Luoyang")

    assert (latitude, longitude) == pytest.approx((34.67345, 112.43684))
    assert client.calls == ["Luoyang"]


def test_geocode_known_fallback_city_does_not_need_network():
    latitude, longitude = services._geocode(None, "南京")

    assert (latitude, longitude) == services.CITY_FALLBACK["南京"]


def test_geocode_unknown_city_raises_city_not_found():
    client = _FakeGeocodeClient({})

    with pytest.raises(services.HomeServiceError) as info:
        services._geocode(client, "不存在的地方")

    assert info.value.code == "city_not_found"
    assert info.value.status == 404


def test_geocode_network_error_maps_to_weather_unavailable():
    client = _FakeGeocodeClient({"洛阳": httpx.ConnectError("boom")})

    with pytest.raises(services.HomeServiceError) as info:
        services._geocode(client, "洛阳")

    assert info.value.code == "weather_unavailable"
    assert info.value.status == 503


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
