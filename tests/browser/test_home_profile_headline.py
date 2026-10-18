"""首页大字编辑 + 我的空间面板的浏览器回归。

只跑单文件：pytest tests/browser/test_home_profile_headline.py -q
使用 tests/browser/conftest.py 的隔离实例，不触碰 %LOCALAPPDATA% 生产数据。
"""

from playwright.sync_api import expect

DEFAULT_HEADLINE = "把今天，安排清楚。"
HEADLINE_INPUT_LABEL = "首页大字，回车保存，Esc 取消"


def api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ({path, method, body}) => {
            const bootstrap = await (await fetch('/api/v1/bootstrap')).json();
            const response = await fetch('/api/v1' + path, {
                method,
                headers: {'X-Workbench-Token': bootstrap.token, 'Content-Type': 'application/json'},
                ...(body === null ? {} : {body: JSON.stringify(body)}),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(JSON.stringify(data));
            return data;
        }""",
        {"path": path, "method": method, "body": body},
    )


def headline(page):
    return page.get_by_role("heading", name="我的一天", exact=True)


def headline_editor(page):
    return page.get_by_label(HEADLINE_INPUT_LABEL, exact=True)


def open_panel(page, trigger="#header-avatar"):
    page.locator(trigger).click()
    panel = page.locator("#mySpacePanel")
    expect(panel).to_be_visible()
    return panel


# --------------------------------------------------------------------------- #
# 首页大字
# --------------------------------------------------------------------------- #


def test_headline_edit_persists_after_reload(ui):
    page, app, root = ui
    title = headline(page)
    expect(title).to_have_text(DEFAULT_HEADLINE)

    title.click()
    editor = headline_editor(page)
    expect(editor).to_be_visible()
    editor.fill("今天只做三件事")
    editor.press("Enter")

    expect(title).to_have_text("今天只做三件事")
    expect(title).to_be_visible()
    assert api(page, "/preferences")["heroHeadline"] == "今天只做三件事"

    page.reload(wait_until="networkidle")
    expect(headline(page)).to_have_text("今天只做三件事")


def test_headline_edit_via_button_and_blur_saves(ui):
    page, app, root = ui
    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    expect(editor).to_be_visible()
    editor.fill("专注一件事")
    # 失焦保存
    page.locator("#header-date").click()
    expect(headline(page)).to_have_text("专注一件事")
    assert api(page, "/preferences")["heroHeadline"] == "专注一件事"


def test_blur_save_does_not_steal_focus_from_next_input(ui):
    page, app, root = ui
    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    editor.fill("失焦后焦点应该留在下一个输入框")
    search = page.locator("#globalSearch")
    search.click()
    expect(headline(page)).to_have_text("失焦后焦点应该留在下一个输入框")
    page.wait_for_timeout(300)
    assert page.evaluate("document.activeElement && document.activeElement.id") == "globalSearch"


def test_ime_composing_enter_does_not_save_headline(ui):
    page, app, root = ui
    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    editor.fill("输入法候选")
    editor.evaluate(
        "el => el.dispatchEvent(new KeyboardEvent('keydown',"
        "{key:'Enter',isComposing:true,bubbles:true,cancelable:true}))"
    )
    expect(editor).to_be_visible()
    assert api(page, "/preferences")["heroHeadline"] == ""


def test_clearing_headline_restores_default(ui):
    page, app, root = ui
    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    editor.fill("会被清掉的大字")
    editor.press("Enter")
    expect(headline(page)).to_have_text("会被清掉的大字")

    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    editor.fill("")
    editor.press("Enter")

    expect(headline(page)).to_have_text(DEFAULT_HEADLINE)
    assert api(page, "/preferences")["heroHeadline"] == ""
    page.reload(wait_until="networkidle")
    expect(headline(page)).to_have_text(DEFAULT_HEADLINE)


def test_escape_cancels_headline_edit_without_saving(ui):
    page, app, root = ui
    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    expect(editor).to_be_visible()
    editor.fill("不应该被保存的大字")
    editor.press("Escape")

    expect(editor).to_be_hidden()
    expect(headline(page)).to_have_text(DEFAULT_HEADLINE)
    expect(headline(page)).to_be_visible()
    assert api(page, "/preferences")["heroHeadline"] == ""


def test_headline_keeps_working_while_home_polling(ui):
    page, app, root = ui
    title = headline(page)
    title.click()
    editor = headline_editor(page)
    editor.fill("轮询期间也不会被覆盖")
    # 等首页轮询（约 2s 一次）完成至少一轮，编辑态内容与页面均不被重挂载
    page.wait_for_timeout(2600)
    expect(editor).to_be_visible()
    expect(editor).to_have_value("轮询期间也不会被覆盖")
    editor.press("Enter")
    expect(title).to_have_text("轮询期间也不会被覆盖")


# --------------------------------------------------------------------------- #
# 我的空间：面板开关 / 资料编辑 / 今日概览
# --------------------------------------------------------------------------- #


def test_my_space_panel_opens_and_closes(ui):
    page, app, root = ui
    avatar = page.locator("#header-avatar")
    expect(avatar).to_be_visible()
    assert "「我的空间」待接入" not in page.content()

    panel = open_panel(page)
    expect(avatar).to_have_attribute("aria-expanded", "true")
    # 打开时焦点可达：焦点落在面板内的资料编辑入口
    expect(panel.get_by_role("button", name="编辑显示名", exact=True)).to_be_focused()
    expect(panel).to_contain_text("今日概览")

    # 点面板外关闭
    page.locator("#header-date").click()
    expect(panel).to_be_hidden()
    expect(avatar).to_have_attribute("aria-expanded", "false")

    # Esc 关闭
    open_panel(page)
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()

    # 再点头像关闭
    open_panel(page)
    avatar.click()
    expect(panel).to_be_hidden()
    expect(avatar).to_have_attribute("aria-expanded", "false")


def test_profile_edits_persist_and_avatars_follow_display_name(ui):
    page, app, root = ui
    avatar = page.locator("#header-avatar")
    expect(avatar).to_have_text("林")

    panel = open_panel(page)
    panel.get_by_role("button", name="编辑显示名", exact=True).click()
    name_input = panel.get_by_label("显示名，回车保存，Esc 取消", exact=True)
    name_input.fill("周同学")
    name_input.press("Enter")
    expect(panel.locator(".wb-space-name")).to_have_text("周同学")
    expect(avatar).to_have_text("周")

    panel.get_by_role("button", name="编辑签名", exact=True).click()
    signature_input = panel.get_by_label("签名，回车保存，Esc 取消", exact=True)
    signature_input.fill("今天也要好好生活")
    signature_input.press("Enter")
    expect(panel.locator(".wb-space-sign")).to_have_text("今天也要好好生活")

    saved = api(page, "/preferences")["profile"]
    assert saved == {"displayName": "周同学", "signature": "今天也要好好生活"}

    # 手机端头像与刷新后保持一致（同源持久化）
    page.reload(wait_until="networkidle")
    expect(avatar).to_have_text("周")
    mobile = page.locator("#mobile-avatar")
    expect(mobile).to_have_text("周")
    # 侧栏 #my-space 保持隐藏，但显示名/签名同步
    assert page.locator("#my-space").is_hidden()
    assert page.evaluate("document.querySelector('#my-space-profile').textContent") == "周同学 · 今天也要好好生活"
    page.locator("#header-avatar").click()
    panel = page.locator("#mySpacePanel")
    expect(panel.locator(".wb-space-name")).to_have_text("周同学")
    expect(panel.locator(".wb-space-sign")).to_have_text("今天也要好好生活")


def test_profile_edit_escape_cancels(ui):
    page, app, root = ui
    panel = open_panel(page)
    panel.get_by_role("button", name="编辑显示名", exact=True).click()
    name_input = panel.get_by_label("显示名，回车保存，Esc 取消", exact=True)
    name_input.fill("不保存的名字")
    name_input.press("Escape")
    expect(panel.locator(".wb-space-name")).to_have_text("林同学")
    assert api(page, "/preferences")["profile"]["displayName"] == "林同学"


def test_my_space_overview_shows_today_stats(ui):
    page, app, root = ui
    api(page, "/notes", "POST", {"text": "面板概览用的随手记"})
    panel = open_panel(page)
    expect(panel).to_contain_text("今日概览")
    expect(panel.get_by_role("button", name="设置", exact=True)).to_be_visible()
    expect(panel.get_by_role("button", name="退出工作台", exact=True)).to_be_visible()
    stats = panel.locator(".wb-space-stat")
    expect(stats).to_have_count(3)
    page.wait_for_function(
        "() => [...document.querySelectorAll('#mySpacePanel .wb-space-stat-value')].every(node => node.textContent !== '…')"
    )
    values = panel.locator(".wb-space-stat-value").all_text_contents()
    assert "/" in values[0], values
    assert int(values[1]) >= 1, values
    assert values[2] != "…", values


def test_my_space_overview_degrades_when_services_fail(ui):
    page, app, root = ui
    for pattern in ["**/api/v1/tasks*", "**/api/v1/notes*", "**/api/v1/projects*"]:
        page.route(pattern, lambda route: route.fulfill(status=500, json={"error": {"code": "boom", "message": "服务不可用"}}))
    panel = open_panel(page)
    expect(panel).to_contain_text("今日概览")
    expect(panel).to_contain_text("暂不可用")
    # 概览失败不阻塞面板快捷操作
    expect(panel.get_by_role("button", name="设置", exact=True)).to_be_visible()
    expect(panel.get_by_role("button", name="退出工作台", exact=True)).to_be_visible()


def test_panel_stays_in_390px_viewport_and_resize_keeps_inputs(ui):
    page, app, root = ui
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="networkidle")

    draft = page.get_by_label("随手记输入", exact=True)
    draft.fill("调整窗口前写了一半的随手记")
    mobile = page.locator("#mobile-avatar")
    expect(mobile).to_be_visible()
    panel = open_panel(page, "#mobile-avatar")

    box = panel.bounding_box()
    assert box["x"] >= 0, box
    assert box["x"] + box["width"] <= 390 + 0.5, box
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert page.evaluate("document.scrollingElement.scrollWidth<=innerWidth")
    expect(panel.get_by_role("button", name="设置", exact=True)).to_be_in_viewport()

    # resize 不重挂首页、不丢未保存输入，面板仍在视口内
    for width, height in [(1440, 900), (390, 844), (900, 650)]:
        page.set_viewport_size({"width": width, "height": height})
        expect(draft).to_have_value("调整窗口前写了一半的随手记")
        page.wait_for_timeout(200)  # 等 resize 后的重新定位（rAF）
        panel_box = page.locator("#mySpacePanel").bounding_box()
        if page.locator("#mySpacePanel").is_visible():
            assert panel_box["x"] >= 0 and panel_box["x"] + panel_box["width"] <= width + 0.5, (width, panel_box)

    page.set_viewport_size({"width": 390, "height": 844})
    page.keyboard.press("Escape")
    expect(page.locator("#mySpacePanel")).to_be_hidden()
    assert errors == []


def test_no_script_errors_on_home_and_panel_interactions(ui):
    page, app, root = ui
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.reload(wait_until="networkidle")
    expect(headline(page)).to_be_visible()

    page.get_by_role("button", name="编辑首页大字", exact=True).click()
    editor = headline_editor(page)
    editor.fill("脚本错误检查的大字")
    editor.press("Enter")
    expect(headline(page)).to_have_text("脚本错误检查的大字")

    panel = open_panel(page)
    expect(panel.get_by_role("button", name="编辑显示名", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    page.wait_for_timeout(2200)
    assert errors == []
