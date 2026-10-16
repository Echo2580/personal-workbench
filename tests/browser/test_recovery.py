from playwright.sync_api import expect


def test_poll_keeps_keyboard_focus_and_disconnect_disables_actions(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    run = page.get_by_role("button", name="启动项目", exact=True)
    run.focus()
    page.wait_for_timeout(2400)
    expect(run).to_be_focused()
    page.route("**/api/v1/projects", lambda r: r.abort())
    expect(
        page.get_by_text("服务已断开，启动与停止暂不可用。正在重新连接…")
    ).to_be_visible(timeout=7000)
    expect(run).to_be_disabled()
    page.unroute("**/api/v1/projects")
    expect(run).to_be_enabled(timeout=12000)
