import re

import pytest
from playwright.sync_api import expect


def test_manual_internal_directory_shows_real_root_hint(ui):
    page, app, root = ui
    project = root / "项目 Alpha"
    selected = project / ".venv" / "Scripts"
    selected.mkdir(parents=True)
    page.goto(page.url.split("#")[0] + "#/projects")
    page.get_by_role("button", name="添加项目", exact=True).click()
    dialog = page.get_by_role("dialog", name="添加项目")
    dialog.get_by_label("项目目录").fill(str(selected))
    dialog.get_by_role("button", name="添加", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("请改为添加项目根目录")
    expect(dialog.get_by_role("alert")).to_contain_text(str(project))
    assert app.state.projects.manual == []


@pytest.mark.parametrize("width", [1440, 390])
def test_failed_run_displays_frozen_command_cwd_and_exit_code(ui, width):
    page, app, root = ui
    page.set_viewport_size({"width": width, "height": 900})
    service = app.state.projects
    project = service.snapshot()["projects"][0]
    project["recipes"][0]["args"] = ["previous-entry.py"]
    run = {
        "id": "diagnostic-fixture",
        "kind": "run",
        "project_id": project["id"],
        "recipe_id": project["recipes"][0]["id"],
        "status": "failed",
        "exit_code": 3,
        "exit_reason": "process_exit",
        "created_at": "2026-10-24T12:00:00+08:00",
        "project_snapshot": project,
    }
    with service.runtime.lock:
        service.runtime.runs[run["id"]] = run
    page.goto(page.url.split("#")[0] + "#/projects")
    card = page.locator(".project-card").filter(has_text="项目 Alpha")
    details = card.locator(".launch-diagnostics")
    expect(details).to_contain_text("退出码：3")
    expect(details).to_contain_text("previous-entry.py")
    expect(details).to_contain_text(
        re.compile(re.escape(str(root / "项目 Alpha")), re.I)
    )
    expect(details).to_contain_text("未保存终端输出")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    details.screenshot(path=str(root.parent / "launcher-diagnostics.png"))
