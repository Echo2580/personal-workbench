from playwright.sync_api import expect


def test_late_module_import_cannot_replace_newer_page(ui):
    page, app, root = ui
    held = []
    page.route("**/modules/projects/page.js", lambda route: held.append(route))
    page.get_by_role("button", name="进入项目启动器").click()
    page.wait_for_timeout(150)
    assert held
    page.get_by_role("button", name="工作台首页", exact=True).click()
    expect(page.get_by_role("heading", name="工作台", exact=True)).to_be_visible()
    for route in held:
        route.fulfill(response=route.fetch())
    page.wait_for_timeout(400)
    expect(page.get_by_role("heading", name="工作台", exact=True)).to_be_visible()
