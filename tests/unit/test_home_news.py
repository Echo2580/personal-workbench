"""世界快讯：RSS 解析、AI 筛选、缓存与降级。"""

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
    news._curated_cache["fetched_at"] = ""
    news._curated_cache["payload"] = None
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


def test_build_briefing_uses_curator_picks(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    news.collect_items(refresh=True)
    model = MockNewsCurator(indexes=[2, 4, 6], summaries=["值得关注一", "值得关注二", "值得关注三"])
    payload = news.build_briefing(tmp_path, False, model)
    assert payload["aiUsed"] is True
    assert len(payload["items"]) == 3
    # 候选按发布时间倒序：标题 8,7,6,...；模型选第 2/4/6 条 => 7/5/3
    titles = [item["title"] for item in payload["items"]]
    assert titles == ["真实新闻标题 7", "真实新闻标题 5", "真实新闻标题 3"]
    assert [item["summary"] for item in payload["items"]] == ["值得关注一", "值得关注二", "值得关注三"]
    # 标题/链接必须原样来自 RSS，模型只能加 summary
    assert payload["items"][0]["url"] == "https://example.com/7"
    assert model.calls  # 确实调用了模型


def test_build_briefing_falls_back_when_curator_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    news.collect_items(refresh=True)
    model = MockNewsCurator(error=RuntimeError("模型不可用"))
    payload = news.build_briefing(tmp_path, False, model)
    assert payload["aiUsed"] is False
    assert payload["aiError"]
    assert len(payload["items"]) == 5  # 退回纯标题（不足 5 条则全部）
    assert all(item["summary"] == "" for item in payload["items"])


def test_build_briefing_falls_back_when_indexes_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    news.collect_items(refresh=True)
    model = MockNewsCurator(indexes=[99, 99, 99])
    payload = news.build_briefing(tmp_path, False, model)
    assert payload["aiUsed"] is False
    assert len(payload["items"]) == 5


def test_build_briefing_reuses_curation_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    news.collect_items(refresh=True)
    model = MockNewsCurator(indexes=[1, 2, 3])
    first = news.build_briefing(tmp_path, False, model)
    calls_after_first = len(model.calls)
    second = news.build_briefing(tmp_path, False, MockNewsCurator(indexes=[1, 2, 3]))
    assert second["fetchedAt"] == first["fetchedAt"]
    assert len(model.calls) == calls_after_first  # 第二次命中缓存，不再调模型


def test_news_endpoint_requires_token(client):
    assert client.get("/api/v1/world-news").status_code == 403


def test_news_endpoint_returns_items(client, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: make_items())
    app = client.app
    app.state.news_model = MockNewsCurator(indexes=[1, 2, 3])
    response = client.get("/api/v1/world-news?refresh=1", headers=headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["aiUsed"] is True
    assert len(body["items"]) == 3
    assert body["items"][0]["url"].startswith("https://example.com/")
    assert body["sourceCount"] >= 1


def test_news_endpoint_error_when_no_sources(client, monkeypatch):
    monkeypatch.setattr(news, "_fetch_feed", lambda feed: [])
    news._cache["items"] = []
    news._cache["fetched_at"] = 0.0
    response = client.get("/api/v1/world-news?refresh=1", headers=headers(client))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "news_unavailable"
