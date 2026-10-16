from playwright.sync_api import expect


def test_settings_and_manual_project(ui):
    page, app, root = ui
    page.get_by_role("button", name="设置", exact=True).click()
    expect(page.get_by_role("heading", name="扫描目录", exact=True)).to_be_visible()
    page.get_by_text("扫描选项", exact=True).click()
    page.get_by_label("扫描周期（秒）").fill("20")
    page.get_by_role("button", name="保存设置").click()
    expect(page.get_by_role("status").filter(has_text="设置已保存")).to_be_visible()
    assert app.state.projects.get_settings()["settings"]["scan_interval_seconds"] == 20
