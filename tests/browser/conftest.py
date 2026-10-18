import threading, time, socket
import pytest, uvicorn
from playwright.sync_api import sync_playwright
from app.main import create_app
from app.modules.home import services as home_services
from app.modules.home.news_model import MockNewsCurator
from app.modules.projects.models import ProjectSettings


def _fake_weather(city):
    return {
        "city": city,
        "temperature": 23,
        "condition": "多云",
        "high": 26,
        "low": 18,
        "humidity": 61,
        "wind": 8.0,
        "forecast": [{"time": "17:00", "temperature": 24}],
        "fetchedAt": "2026-10-18T16:00:00+08:00",
        "cached": False,
    }


NEWS_ITEMS = [
    {"title": f"测试新闻标题 {i}", "url": f"https://example.com/news/{i}", "source": "测试源", "category": "国际", "publishedAt": "2026-10-18T12:00+08:00"}
    for i in range(1, 7)
]


def _fake_feed(feed):
    return [dict(item, source=feed["name"]) for item in NEWS_ITEMS[:2]]


@pytest.fixture
def ui(tmp_path, monkeypatch):
    # 首页会请求天气/新闻：浏览器回归不访问外网、不调用真实模型。
    monkeypatch.setattr(home_services, "fetch_weather", _fake_weather)
    from app.modules.home import news as home_news

    monkeypatch.setattr(home_news, "_fetch_feed", _fake_feed)
    root = tmp_path / "projects"
    root.mkdir()
    p = root / "项目 Alpha"
    p.mkdir()
    (p / "main.py").write_text(
        "if __name__ == '__main__':\n import time;time.sleep(60)", encoding="utf-8"
    )
    app = create_app(tmp_path / "data")
    app.state.news_model = MockNewsCurator(indexes=[1, 2, 3])
    d = app.state.projects.get_settings()
    app.state.projects.save_settings(ProjectSettings(roots=[str(root)]), d["revision"])
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(5000)
        page.goto(f"http://127.0.0.1:{port}")
        page.wait_for_load_state("networkidle")
        yield page, app, root
        browser.close()
    server.should_exit = True
    thread.join(10)
