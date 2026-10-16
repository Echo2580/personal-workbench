from playwright.sync_api import expect


def test_remove_cancel_rescan_reload_restore(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_be_visible()
    page.get_by_role("button", name="从工作台移除", exact=True).click()
    dialog = page.get_by_role("dialog", name="从工作台移除")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("不删除本地文件", exact=False)).to_be_visible()
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_be_visible()
    page.get_by_role("button", name="从工作台移除", exact=True).click()
    dialog.get_by_role("button", name="确认移除", exact=True).click()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_have_count(0)
    page.get_by_role("button", name="重新扫描", exact=True).click()
    expect(page.get_by_role("button", name="重新扫描", exact=True)).to_be_enabled()
    page.reload()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_have_count(0)
    page.get_by_role("button", name="设置", exact=True).click()
    expect(page.get_by_role("heading", name="已移除项目", exact=True)).to_be_visible()
    expect(page.get_by_text("项目 Alpha", exact=True)).to_be_visible()
    page.get_by_role("button", name="恢复", exact=True).click()
    expect(page.get_by_text("暂无已移除项目。", exact=True)).to_be_visible()
    page.get_by_role("button", name="项目启动器", exact=True).click()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_be_visible()
    assert (root / "项目 Alpha" / "main.py").is_file()


def test_running_project_cannot_be_removed_in_ui(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="启动项目", exact=True).click()
    page.get_by_role("button", name="确认并执行", exact=True).click()
    stop = page.get_by_role("button", name="停止", exact=True)
    expect(stop).to_be_visible(timeout=8000)
    expect(page.get_by_role("button", name="从工作台移除", exact=True)).to_be_disabled()
    stop.click()
    expect(page.get_by_role("button", name="从工作台移除", exact=True)).to_be_enabled(
        timeout=8000
    )


def test_removal_conflict_keeps_dialog_and_project(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="从工作台移除", exact=True).click()
    path = app.state.projects.projects_path
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# other editor\n", encoding="utf-8"
    )
    dialog = page.get_by_role("dialog", name="从工作台移除")
    page.wait_for_timeout(
        2400
    )  # a background poll must not replace this confirmation revision
    dialog.get_by_role("button", name="确认移除", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("配置已被")
    expect(page.get_by_role("heading", name="项目 Alpha")).to_be_visible()
    dialog.get_by_role("button", name="取消", exact=True).click()


def test_old_service_keeps_settings_usable_and_explains_restart(ui):
    page, app, root = ui

    def old_projects(route):
        response = route.fetch()
        data = response.json()
        data.pop("revision", None)
        route.fulfill(response=response, json=data)

    page.route("**/api/v1/projects", old_projects)
    page.route(
        "**/api/v1/projects/removed",
        lambda route: route.fulfill(status=404, json={"detail": "Not Found"}),
    )
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="从工作台移除", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="需要重启工作台")).to_be_visible()
    expect(page.get_by_role("dialog", name="从工作台移除")).to_have_count(0)
    page.get_by_role("button", name="设置", exact=True).click()
    expect(page.get_by_role("heading", name="扫描目录", exact=True)).to_be_visible()
    expect(page.get_by_text("需要重启工作台", exact=False).last).to_be_visible()
    expect(page.get_by_role("button", name="保存设置")).to_be_visible()
