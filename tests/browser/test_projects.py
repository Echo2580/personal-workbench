from playwright.sync_api import expect


def test_search_expand_confirm_launch_stop(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    expect(page.get_by_role("heading", name="项目 Alpha")).to_be_visible()
    search = page.get_by_role("searchbox", name="搜索项目")
    search.fill("missing")
    expect(page.get_by_text("没有匹配的项目")).to_be_visible()
    search.press("Escape")
    page.get_by_role("button", name="配方 2").click()
    expect(page.get_by_role("button", name="编辑配方")).to_be_visible()
    page.get_by_role("button", name="启动项目", exact=True).click()
    expect(page.get_by_role("dialog", name="确认配方")).to_be_visible()
    page.get_by_role("button", name="确认并执行").click()
    expect(page.get_by_role("button", name="停止", exact=True)).to_be_visible(
        timeout=8000
    )
    page.get_by_role("button", name="停止", exact=True).click()
    expect(page.get_by_text("已停止", exact=True).first).to_be_visible(timeout=8000)
