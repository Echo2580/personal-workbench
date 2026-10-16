import json, socket, time, urllib.request
from pathlib import Path
from playwright.sync_api import expect


def test_single_click_process_creation_and_offline_http_readiness(ui):
    page, app, root = ui
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    source = root / "项目 Alpha" / "main.py"
    source.write_text(
        "if __name__ == '__main__':\n from http.server import HTTPServer,BaseHTTPRequestHandler\n class H(BaseHTTPRequestHandler):\n  def do_GET(self):\n   self.send_response(200);self.end_headers();self.wfile.write(b'ready')\n HTTPServer(('127.0.0.1',"
        + str(port)
        + "),H).serve_forever()\n",
        encoding="utf-8",
    )
    service = app.state.projects
    project = next(
        p for p in service.snapshot()["projects"] if p["name"] == "项目 Alpha"
    )
    doc = service.get_recipes(project["id"])
    r = next(r for r in doc["recipes"] if r["kind"] == "command")
    service.approve(project["id"], r["id"], r["fingerprint"])
    page.get_by_role("button", name="进入项目启动器").click()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    measurements = []
    for _ in range(3):
        run = page.get_by_role("button", name="启动项目", exact=True)
        expect(run).to_be_enabled()
        started = time.perf_counter()
        with page.expect_response(
            lambda response: (
                "/actions" in response.url and response.request.method == "POST"
            )
        ) as event:
            run.click()
        payload = event.value.json()
        assert payload["run"]["status"] in ("running", "exited")
        creation = time.perf_counter() - started
        deadline = started + 5
        while True:
            try:
                with opener.open(f"http://127.0.0.1:{port}", timeout=0.3) as response:
                    if response.read() == b"ready":
                        break
            except Exception:
                if time.perf_counter() > deadline:
                    raise
                time.sleep(0.02)
        ready = time.perf_counter() - started
        assert creation < 3 and ready < 3
        measurements.append(
            {
                "click_to_managed_run_seconds": round(creation, 4),
                "click_to_fixture_http_ready_seconds": round(ready, 4),
            }
        )
        page.get_by_role("button", name="停止", exact=True).click()
        expect(run).to_be_enabled(timeout=6000)
    evidence = Path("docs/local-evidence")
    evidence.mkdir(exist_ok=True)
    (evidence / "launch-timing.json").write_text(
        json.dumps(
            {
                "scope": "offline test fixture, not real project business readiness",
                "trials": measurements,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
