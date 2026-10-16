"""Read the live catalog; verify removal in disposable data without running projects."""

import argparse
import json
import socket
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.main import create_app
from app.modules.projects.models import ProjectSettings, RecipeSet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-url", default="http://127.0.0.1:17843")
    parser.add_argument(
        "--out", type=Path, default=Path("docs/local-evidence/screenshots")
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.live_url.rstrip("/")
    token = json.load(urllib.request.urlopen(base + "/api/v1/bootstrap", timeout=5))[
        "token"
    ]

    def live(path):
        req = urllib.request.Request(
            base + "/api/v1" + path, headers={"X-Workbench-Token": token}
        )
        return json.load(urllib.request.urlopen(req, timeout=5))

    catalog = live("/projects")["projects"]
    settings = live("/settings/projects")["settings"]
    active_before = {
        r["id"]
        for r in live("/projects/runs")["runs"]
        if r["status"] in ("running", "launching", "stopping")
    }
    if not catalog:
        raise RuntimeError(
            "The live catalog is empty; do not fabricate screenshot data."
        )
    with tempfile.TemporaryDirectory(prefix="workbench-removal-review-") as temporary:
        app = create_app(Path(temporary) / "data")
        service = app.state.projects
        doc = service.get_settings()
        service.save_settings(ProjectSettings.model_validate(settings), doc["revision"])
        for _ in range(200):
            if not service.is_scanning:
                break
            time.sleep(0.02)
        for p in catalog:
            if p["manual"]:
                service.add_manual_project(p["path"], p["name"])
            if p["recipe_source"] == "manual":
                saved = live(f"/projects/{p['id']}/recipes")
                for r in saved["recipes"]:
                    r.pop("fingerprint", None)
                service.save_recipes(
                    p["id"],
                    RecipeSet(
                        recipes=saved["recipes"],
                        primary_recipe_id=saved["primary_recipe_id"],
                    ),
                    service.get_recipes(p["id"])["revision"],
                )
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(
            target=lambda: server.run(sockets=[sock]), daemon=True
        )
        thread.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.02)
        errors = []
        checks = []
        selected = next((p for p in catalog if p["name"] == "werewolf"), catalog[0])
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}")
                page.get_by_role("button", name="进入项目启动器").click()
                card = page.locator("#project-" + selected["id"])
                expect(card).to_be_visible()
                page.screenshot(
                    path=str(args.out / "removal-projects-real-1440.png"),
                    full_page=True,
                )
                card.get_by_role("button", name="从工作台移除", exact=True).click()
                dialog = page.get_by_role("dialog", name="从工作台移除")
                expect(dialog).to_be_visible()
                page.screenshot(
                    path=str(args.out / "removal-confirm-real-1440.png"), full_page=True
                )
                dialog.get_by_role("button", name="确认移除", exact=True).click()
                expect(card).to_have_count(0)
                page.get_by_role("button", name="设置", exact=True).click()
                expect(page.get_by_text(selected["name"], exact=True)).to_be_visible()
                page.locator(".toast").filter(has_text="已从工作台移除").wait_for(
                    state="hidden", timeout=10000
                )
                for width, height in [(1440, 900), (600, 800)]:
                    page.set_viewport_size({"width": width, "height": height})
                    section = page.locator("section.settings-panel").filter(
                        has=page.get_by_role("heading", name="已移除项目", exact=True)
                    )
                    section.scroll_into_view_if_needed()
                    checks.append(
                        {
                            "width": width,
                            "horizontal_overflow": page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth"
                            ),
                        }
                    )
                    page.screenshot(
                        path=str(args.out / f"removal-settings-real-{width}.png"),
                        full_page=True,
                    )
                    if width == 1440:
                        section.screenshot(
                            path=str(args.out / "removal-settings-section-real.png")
                        )
                page.set_viewport_size({"width": 1440, "height": 900})
                page.get_by_role("button", name="恢复", exact=True).click()
                expect(page.get_by_text("暂无已移除项目。", exact=True)).to_be_visible()
                page.get_by_role("button", name="项目启动器", exact=True).click()
                expect(card).to_be_visible()
                page.screenshot(
                    path=str(args.out / "removal-restored-real-1440.png"),
                    full_page=True,
                )
                assert len(service.snapshot()["projects"]) == len(catalog)
                assert not service.runs(), (
                    "Isolated review must never launch real recipes."
                )
                browser.close()
        finally:
            server.should_exit = True
            thread.join(10)
    active_after = {
        r["id"]
        for r in live("/projects/runs")["runs"]
        if r["status"] in ("running", "launching", "stopping")
    }
    result = {
        "source": "live catalog, disposable data, no real actions executed",
        "project_count": len(catalog),
        "selected": selected["name"],
        "checks": checks,
        "page_errors": errors,
        "live_active_before": sorted(active_before),
        "live_active_after": sorted(active_after),
    }
    (args.out.parent / "removal-ui-inspection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert not errors and not any(c["horizontal_overflow"] for c in checks)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
