from playwright.sync_api import expect


def test_editor_saves_and_conflict_keeps_draft(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="配方 2").click()
    page.get_by_role("button", name="编辑配方").click()
    dialog = page.get_by_role("dialog", name="编辑配方")
    dialog.get_by_label("配方名称").first.fill("我的运行")
    config = app.state.projects.projects_path
    config.write_text(
        config.read_text(encoding="utf-8") + "\n# 外部修改\n", encoding="utf-8"
    )
    dialog.get_by_role("button", name="保存配方", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("配置已被")
    expect(dialog.get_by_label("配方名称").first).to_have_value("我的运行")
    page.on("dialog", lambda d: d.accept())
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(dialog).not_to_be_visible()


def test_xss_project_name_is_text(ui):
    page, app, root = ui
    p = root / "manual"
    p.mkdir()
    app.state.projects.add_manual_project(p, "<img src=x onerror=alert(1)>")
    page.get_by_role("button", name="进入项目启动器").click()
    expect(
        page.get_by_role("heading", name="<img src=x onerror=alert(1)>")
    ).to_be_visible()
    assert page.locator("main img").count() == 0
