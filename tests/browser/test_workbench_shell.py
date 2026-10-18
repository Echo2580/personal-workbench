from playwright.sync_api import expect


def test_home_routes_planned_keyboard_and_layout(ui):
    page, app, root = ui
    expect(page.get_by_role("heading", name="我的一天", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="快捷导航 规划中")).to_be_disabled()
    page.get_by_role("button", name="进入项目启动器").click()
    page.reload()
    expect(page.get_by_role("heading", name="项目启动器", exact=True)).to_be_visible()
    page.go_back()
    expect(page.get_by_role("heading", name="我的一天", exact=True)).to_be_visible()
    page.goto(page.url.split("#")[0] + "#/unknown")
    expect(page.get_by_role("button", name="返回工作台")).to_be_visible()
    page.get_by_role("button", name="返回工作台").click()
    for width, height in [(1440, 900), (1280, 800), (1024, 768), (600, 800)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.get_by_role("button", name="展开导航").click()
    expect(page.get_by_role("button", name="设置", exact=True)).to_be_visible()


def test_unconfigured_home_offers_settings_and_module_entry(ui):
    page, app, root = ui
    from app.modules.projects.models import ProjectSettings

    service = app.state.projects
    doc = service.get_settings()
    service.save_settings(ProjectSettings(roots=[]), doc["revision"])
    page.reload()
    expect(page.get_by_role("button", name="设置扫描目录", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="进入项目启动器")).to_be_visible()
    page.get_by_role("button", name="设置扫描目录", exact=True).click()
    expect(page.get_by_role("heading", name="扫描目录", exact=True)).to_be_visible()


def test_exit_preview_cancel_preserves_owned_command(ui):
    page, app, root = ui
    service = app.state.projects
    project = service.project(service.snapshot()["projects"][0]["id"])
    recipe = next(r for r in project.recipes if r.kind == "command")
    service.runtime.launch(project, recipe)
    page.get_by_role("button", name="退出工作台", exact=True).click()
    dialog = page.get_by_role("dialog", name="退出工作台")
    expect(dialog.get_by_text("项目 Alpha", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="取消", exact=True).click()
    assert service.runtime.active_count() == 1
