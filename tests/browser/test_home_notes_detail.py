# -*- coding: utf-8 -*-
"""首页随手记：长内容查看、详情/编辑、复制、多行输入的浏览器回归。

只跑单文件：pytest tests/browser/test_home_notes_detail.py -q
使用 tests/browser/conftest.py 的隔离实例，不触碰生产数据。
"""

from playwright.sync_api import expect

DETAIL_TEXT = "#noteDetailModal .whitespace-pre-wrap"


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


def detail_text(page):
    return page.locator(DETAIL_TEXT).evaluate("el => el.textContent")


def open_first_note_detail(page, scope="#scratchCard"):
    trigger = page.locator(f"{scope} button[aria-label^='查看随手记全文']").first
    expect(trigger).to_be_visible()
    trigger.click()
    modal = page.locator("#noteDetailModal")
    expect(modal).to_be_visible()
    return modal


def test_long_note_home_card_opens_full_detail(ui):
    page, app, root = ui
    text = "第一行\n第二行\n" + "长" * 300
    api(page, "/notes", "POST", {"text": text})
    page.reload(wait_until="networkidle")

    # 首页卡片只显示 2 行摘要，完整内容进详情
    summary = page.locator("#scratchCard button[aria-label^='查看随手记全文'] span").first
    clamp = summary.evaluate(
        "el => ({client: el.clientHeight, scroll: el.scrollHeight, clamp: getComputedStyle(el).webkitLineClamp})"
    )
    assert clamp["clamp"] == "2"
    assert clamp["scroll"] > clamp["client"]

    modal = open_first_note_detail(page)
    assert detail_text(page) == text
    assert page.locator(DETAIL_TEXT).evaluate("el => getComputedStyle(el).whiteSpace") == "pre-wrap"
    expect(modal).to_contain_text("创建于")
    expect(modal.get_by_role("button", name="复制全文", exact=True)).to_be_visible()
    expect(modal.get_by_role("button", name="编辑", exact=True)).to_be_visible()

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()


def test_all_notes_drawer_has_view_full_for_each(ui):
    page, app, root = ui
    for index in range(4):
        api(page, "/notes", "POST", {"text": f"第 {index} 条笔记的完整内容\n第二行"})
    page.reload(wait_until="networkidle")

    page.locator("#scratchCard").get_by_role("button", name="查看全部", exact=True).click()
    drawer = page.locator("#notesModal")
    expect(drawer).to_be_visible()
    expect(drawer.locator("#notesAllList [data-note-id]")).to_have_count(4)
    view_all = drawer.locator("#notesAllList").get_by_role("button", name="查看全文", exact=True)
    expect(view_all).to_have_count(4)

    view_all.first.click()
    modal = page.locator("#noteDetailModal")
    expect(modal).to_be_visible()
    assert detail_text(page).startswith("第 ")

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    expect(drawer).to_be_visible()
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()


def test_note_detail_edit_saves_and_persists(ui):
    page, app, root = ui
    created = api(page, "/notes", "POST", {"text": "原始内容"})["item"]
    page.reload(wait_until="networkidle")

    modal = open_first_note_detail(page)
    modal.get_by_role("button", name="编辑", exact=True).click()
    editor = modal.get_by_label("编辑随手记内容", exact=True)
    expect(editor).to_be_visible()
    expect(editor).to_have_value("原始内容")
    editor.fill("编辑后第一行\n编辑后第二行")
    modal.get_by_role("button", name="保存", exact=True).click()

    expect(page.locator("#toast")).to_contain_text("已保存")
    expect(page.locator(DETAIL_TEXT)).to_have_text("编辑后第一行 编辑后第二行")
    assert detail_text(page) == "编辑后第一行\n编辑后第二行"
    items = api(page, "/notes")["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["text"] == "编辑后第一行\n编辑后第二行"

    page.keyboard.press("Escape")
    page.reload(wait_until="networkidle")
    open_first_note_detail(page)
    assert detail_text(page) == "编辑后第一行\n编辑后第二行"


def test_detail_opens_on_top_of_drawer_after_earlier_detail(ui):
    page, app, root = ui
    api(page, "/notes", "POST", {"text": "优先顺序测试\n第二行"})
    page.reload(wait_until="networkidle")

    # 先从首页卡片打开过一次详情并关闭（详情 overlay 已创建）
    open_first_note_detail(page)
    page.keyboard.press("Escape")
    expect(page.locator("#noteDetailModal")).to_be_hidden()

    # 再从抽屉点「查看全文」：详情必须盖在抽屉之上
    page.locator("#scratchCard").get_by_role("button", name="查看全部", exact=True).click()
    drawer = page.locator("#notesModal")
    expect(drawer).to_be_visible()
    drawer.locator("#notesAllList").get_by_role("button", name="查看全文", exact=True).first.click()
    modal = page.locator("#noteDetailModal")
    expect(modal).to_be_visible()
    topmost = page.evaluate(
        """() => {
            const el = document.querySelector('#noteDetailModal .whitespace-pre-wrap');
            const rect = el.getBoundingClientRect();
            const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
            return document.querySelector('#noteDetailModal').contains(hit);
        }"""
    )
    assert topmost
    # 第一次 Esc 只关详情，抽屉仍在；第二次才关抽屉
    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    expect(drawer).to_be_visible()
    page.keyboard.press("Escape")
    expect(drawer).to_be_hidden()


def test_multiline_note_convert_to_task_flattens_title(ui):
    page, app, root = ui
    api(page, "/notes", "POST", {"text": "第一行\n第二行"})
    page.reload(wait_until="networkidle")

    modal = open_first_note_detail(page)
    modal.get_by_role("button", name="转待办", exact=True).click()
    expect(page.locator("#toast")).to_contain_text("已转为待办")
    tasks = api(page, "/tasks?status=all")["tasks"]
    assert [task["title"] for task in tasks] == ["第一行 第二行"]


def test_note_detail_edit_escape_returns_to_view(ui):
    page, app, root = ui
    api(page, "/notes", "POST", {"text": "不要改我"})
    page.reload(wait_until="networkidle")

    modal = open_first_note_detail(page)
    modal.get_by_role("button", name="编辑", exact=True).click()
    editor = modal.get_by_label("编辑随手记内容", exact=True)
    editor.fill("改了一半")
    editor.press("Escape")

    expect(editor).to_be_hidden()
    expect(page.locator(DETAIL_TEXT)).to_have_text("不要改我")
    expect(modal).to_be_visible()


def test_scratch_textarea_enter_saves_shift_enter_newline(ui):
    page, app, root = ui
    editor = page.get_by_label("随手记输入", exact=True)
    expect(editor).to_be_visible()
    editor.click()
    page.keyboard.type("第一行")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("第二行")
    page.keyboard.press("Enter")

    expect(page.locator("#toast")).to_contain_text("已记下")
    expect(editor).to_have_value("")
    api_text = api(page, "/notes")["items"][0]["text"]
    assert api_text == "第一行\n第二行"

    page.reload(wait_until="networkidle")
    modal = open_first_note_detail(page)
    assert detail_text(page) == "第一行\n第二行"
    page.keyboard.press("Escape")


def test_note_detail_copy_and_390_layout(ui):
    page, app, root = ui
    text = "第一行\n第二行\n" + "长" * 200
    api(page, "/notes", "POST", {"text": text})
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="networkidle")

    modal = open_first_note_detail(page)
    box = page.locator("#noteDetailModal > div").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390 + 0.5, box
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    stubbed = page.evaluate(
        """() => {
            try {
                Object.defineProperty(navigator, 'clipboard', {
                    configurable: true,
                    value: {writeText: (value) => { window.__copied = value; return Promise.resolve(); }},
                });
                return true;
            } catch (error) { return false; }
        }"""
    )
    if stubbed:
        modal.get_by_role("button", name="复制全文", exact=True).click()
        expect(page.locator("#toast")).to_contain_text("已复制全文")
        assert page.evaluate("window.__copied") == text
        # Clipboard 拒绝时要有可见失败提示
        page.evaluate(
            """() => Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: {writeText: () => Promise.reject(new Error('denied'))},
            })"""
        )
        modal.get_by_role("button", name="复制全文", exact=True).click()
        expect(page.locator("#toast")).to_contain_text("复制失败")
    else:
        expect(modal.get_by_role("button", name="复制全文", exact=True)).to_be_visible()

    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
