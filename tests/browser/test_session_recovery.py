from playwright.sync_api import expect
from app.core.security import create_session_token


def test_rotated_service_session_recovers_on_poll(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_be_visible()
    app.state.token = create_session_token()
    page.wait_for_timeout(2600)
    expect(page.get_by_role("button", name="启动项目", exact=True)).to_be_enabled()
    page.get_by_role("button", name="配方 2").click()
    page.get_by_role("button", name="编辑配方").click()
    expect(page.get_by_role("dialog", name="编辑配方")).to_be_visible()
