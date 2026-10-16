import threading, time, socket
import pytest, uvicorn
from playwright.sync_api import sync_playwright
from app.main import create_app
from app.modules.projects.models import ProjectSettings


@pytest.fixture
def ui(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    p = root / "项目 Alpha"
    p.mkdir()
    (p / "main.py").write_text(
        "if __name__ == '__main__':\n import time;time.sleep(60)", encoding="utf-8"
    )
    app = create_app(tmp_path / "data")
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
