import threading, time, socket
import pytest, uvicorn
from playwright.sync_api import sync_playwright
from app.main import create_app
from app.modules.home import services as home_services
from app.modules.home.joke_model import MockJokeModel
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


@pytest.fixture
def ui(tmp_path, monkeypatch):
    # 首页会请求天气/段子：浏览器回归不访问外网、不调用真实模型。
    monkeypatch.setattr(home_services, "fetch_weather", _fake_weather)
    root = tmp_path / "projects"
    root.mkdir()
    p = root / "项目 Alpha"
    p.mkdir()
    (p / "main.py").write_text(
        "if __name__ == '__main__':\n import time;time.sleep(60)", encoding="utf-8"
    )
    app = create_app(tmp_path / "data")
    app.state.joke_model = MockJokeModel(joke="测试段子：今天的待办比昨天更懂事了。")
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
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(5000)
        page.goto(f"http://127.0.0.1:{port}")
        page.wait_for_load_state("networkidle")
        yield page, app, root
        browser.close()
    server.should_exit = True
    thread.join(10)
