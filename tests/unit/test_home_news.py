"""世界快讯：RSS 解析、AI 筛选、按日存档与降级。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.home import news
from app.modules.home.news_model import MockNewsCurator

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>测试源</title>
<item><title>全球科技峰会发布新协议</title><link>https://example.com/a</link>
<pubDate>Sun, 18 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>多地推进教育数字化改革</title><link>https://example.com/b</link>
<pubDate>Sun, 18 Oct 2026 07:30:00 GMT</pubDate></item>
<item><title>没有链接的条目</title></item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom 源</title>
<entry><title>AI 模型发布新版本</title><link href="https://example.com/atom"/>
<updated>2026-10-18T09:00:00Z</updated></entry>
</feed>"""


def make_items(count=8):
    return [
        {
            "title": f"真实新闻标题 {index}",
            "url": f"https://example.com/{index}",
            "source": "测试源",
            "category": "国际",
            "publishedAt": f"2026-10-18T{index:02d}:00+08:00",
        }
        for index in range(1, count + 1)
    ]


@pytest.fixture(autouse=True)
def _reset_news_caches():
    news._cache["items"] = []
    news._cache["fetched_at"] = 0.0
    yield


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app, base_url="http://127.0.0.1:17843")


def headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/bootstrap").json()["token"]
    return {"X-Workbench-Token": token, "Origin": "http://127.0.0.1:17843"}


def test_parse_rss_and_atom():
    feed = {"id": "t", "name": "测试源", "category": "要闻", "url": "https://example.com/rss"}
    items = news.parse_feed(RSS_SAMPLE, feed)
    assert [item["title"] for item in items] == ["全球科技峰会发布新协议", "多地推进教育数字化改革"]
    assert all(item["url"].startswith("https://example.com/") for item in items)
    assert items[0]["publishedAt"].startswith("2026-10-18T16:00")

    atom_items = news.parse_feed(ATOM_SAMPLE, feed)
    assert atom_items and atom_items[0]["url"] == "https://example.com/atom"


def test_first_visit_curates_then_same_day_is_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    model = MockNewsCurator(indexes=[2, 4, 6], summaries=["值得关注一", "值得关注二", "值得关注三"])
    first = news.build_briefing(tmp_path, False, model)
    assert first["aiUsed"] is True
    assert first["cached"] is False
    assert len(first["items"]) == 3
    titles = [item["title"] for item in first["items"]]
    # 候选按发布时间倒序：标题 8,7,6,...；模型选第 2/4/6 条 => 7/5/3
    assert titles == ["真实新闻标题 7", "真实新闻标题 5", "真实新闻标题 3"]
    assert first["items"][0]["summary"] == "值得关注一"
    assert first["items"][0]["url"] == "https://example.com/7"
    assert len(model.calls) == 1

    # 同一天再次进入：直接读存档，不抓取、不调模型
    fetches = []
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: fetches.append(feed["id"]) or make_items())
    other = MockNewsCurator(indexes=[1, 2, 3])
    second = news.build_briefing(tmp_path, False, other)
    assert second["cached"] is True
    assert second["items"] == first["items"]
    assert other.calls == []
    assert fetches == []


def test_refresh_forces_fetch_and_ai(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    first = news.build_briefing(tmp_path, False, MockNewsCurator(indexes=[1, 2, 3]))
    model = MockNewsCurator(indexes=[2, 3, 4])
    refreshed = news.build_briefing(tmp_path, True, model)
    assert refreshed["cached"] is False
    assert len(model.calls) == 1
    assert refreshed["date"] == first["date"]


def test_same_day_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    news.build_briefing(tmp_path, False, MockNewsCurator(indexes=[1, 2, 3]))
    news._cache["items"] = []
    news._cache["fetched_at"] = 0.0

    model = MockNewsCurator(indexes=[2, 3, 4])
    cached = news.build_briefing(tmp_path, False, model)
    assert cached["cached"] is True
    assert model.calls == []


def test_falls_back_to_saved_when_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    saved = news.build_briefing(tmp_path, False, MockNewsCurator(indexes=[1, 2, 3]))

    monkeypatch.setattr(news, "_fetch_feed", lambda feed: [])
    stale = news.build_briefing(tmp_path, True, MockNewsCurator(indexes=[1, 2, 3]))
    assert stale["cached"] is True
    assert stale["stale"] is True
    assert stale["items"] == saved["items"]


def test_curator_failure_falls_back_to_headlines(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    model = MockNewsCurator(error=RuntimeError("模型不可用"))
    payload = news.build_briefing(tmp_path, True, model)
    assert payload["aiUsed"] is False
    assert payload["aiError"]
    assert len(payload["items"]) == 5
    assert all(item["summary"] == "" for item in payload["items"])


def test_invalid_indexes_fall_back_to_headlines(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    payload = news.build_briefing(tmp_path, True, MockNewsCurator(indexes=[99, 99, 99]))
    assert payload["aiUsed"] is False
    assert len(payload["items"]) == 5


def test_news_endpoint_requires_token(client):
    assert client.get("/api/v1/world-news").status_code == 403


def test_news_endpoint_first_visit_then_cached(client, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    app = client.app
    app.state.news_model = MockNewsCurator(indexes=[1, 2, 3])
    response = client.get("/api/v1/world-news?refresh=1", headers=headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["aiUsed"] is True
    assert len(body["items"]) == 3
    assert body["items"][0]["url"].startswith("https://example.com/")

    # 同一天普通进入：命中存档
    fetches = []
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: fetches.append(1) or [])
    app.state.news_model = MockNewsCurator(indexes=[1, 2, 3])
    again = client.get("/api/v1/world-news", headers=headers(client))
    assert again.status_code == 200
    assert again.json()["cached"] is True
    assert fetches == []
    assert app.state.news_model.calls == []


def test_news_endpoint_error_when_no_sources(client, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: [])
    response = client.get("/api/v1/world-news?refresh=1", headers=headers(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "news_unavailable"
