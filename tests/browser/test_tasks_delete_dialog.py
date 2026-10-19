# -*- coding: utf-8 -*-
"""待办删除确认弹窗的浏览器回归。

只跑单文件：pytest tests/browser/test_tasks_delete_dialog.py -q
使用 tests/browser/conftest.py 的隔离实例，不触碰生产数据。
"""

from playwright.sync_api import expect

DIALOG = "#delete-task-dialog"


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


def create_task(page, title):
    return api(page, "/tasks", "POST", {"title": title})["task"]


def tasks_page(page):
    page.goto(page.url.split("#")[0] + "#/tasks")
    expect(page.locator(".tasks-scope #view-list")).to_be_visible()


def row(page, title):
    return page.locator(".tasks-scope .task-row", has_text=title)


def open_dialog_from_row(page, title):
    row(page, title).locator(".task-row-delete").click()
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    return dialog


def task_ids(page):
    return [task["id"] for task in api(page, "/tasks?status=all")["tasks"]]


def test_row_delete_opens_confirm_dialog_with_task_name(ui):
    page, _app, _root = ui
    task = create_task(page, "要删除的报销单")
    tasks_page(page)
    expect(row(page, "要删除的报销单")).to_be_visible()

    dialog = open_dialog_from_row(page, "要删除的报销单")
    expect(dialog.locator("#delete-task-title")).to_have_text("删除待办？")
    expect(dialog.locator("#delete-task-name")).to_have_text("要删除的报销单")
    expect(dialog.get_by_role("button", name="删除待办", exact=True)).to_be_visible()
    expect(page.get_by_role("dialog", name="删除待办？")).to_have_count(1)
    assert dialog.get_attribute("aria-describedby") == "delete-task-note"
    # 默认焦点在「取消」，避免误按回车直接删除
    assert page.evaluate("document.activeElement && document.activeElement.id") == "btn-delete-dialog-cancel"

    box = dialog.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 1440 + 0.5, box
    assert abs((box["x"] + box["width"] / 2) - 720) < 40, box

    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(row(page, "要删除的报销单")).to_be_visible()
    assert task["id"] in task_ids(page)


def test_escape_and_backdrop_close_dialog_without_deleting(ui):
    page, _app, _root = ui
    task = create_task(page, "不能误删的待办")
    tasks_page(page)

    dialog = open_dialog_from_row(page, "不能误删的待办")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    assert task["id"] in task_ids(page)

    dialog = open_dialog_from_row(page, "不能误删的待办")
    page.mouse.click(8, 8)  # 点击 dialog 背后的遮罩区域
    expect(dialog).to_be_hidden()
    assert task["id"] in task_ids(page)


def test_cancel_and_escape_restore_focus_to_row_delete_button(ui):
    page, _app, _root = ui
    create_task(page, "取消后焦点归位")
    tasks_page(page)
    trigger = row(page, "取消后焦点归位").locator(".task-row-delete")

    trigger.click()
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(dialog).to_be_hidden()
    assert page.evaluate(
        "document.activeElement && document.activeElement.getAttribute('aria-label')"
    ) == "删除待办：取消后焦点归位"

    trigger.click()
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    assert page.evaluate(
        "document.activeElement && document.activeElement.getAttribute('aria-label')"
    ) == "删除待办：取消后焦点归位"


def test_detail_bottom_delete_button_opens_same_dialog(ui):
    page, _app, _root = ui
    create_task(page, "详情底部删除入口")
    tasks_page(page)
    row(page, "详情底部删除入口").locator(".task-detail-link").click()
    expect(page.locator(".tasks-scope #view-detail")).to_be_visible()

    page.locator("#btn-delete").click()
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    expect(dialog.locator("#delete-task-name")).to_have_text("详情底部删除入口")
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".tasks-scope #view-detail")).to_be_visible()


def test_double_confirm_sends_single_delete_request(ui):
    page, _app, _root = ui
    task = create_task(page, "连点两次只删一次")
    tasks_page(page)
    deletes = []
    page.on("request", lambda request: deletes.append(request) if request.method == "DELETE" else None)

    open_dialog_from_row(page, "连点两次只删一次")
    page.evaluate(
        """() => {
            const btn = document.querySelector('#btn-delete-dialog-confirm');
            btn.click();
            btn.click();
        }"""
    )
    expect(page.locator(DIALOG)).to_be_hidden()
    expect(page.locator("#tasks-toast")).to_contain_text("已删除待办")
    page.wait_for_timeout(150)
    assert len(deletes) == 1, [request.url for request in deletes]
    assert task["id"] not in task_ids(page)


def test_confirm_deletes_task_and_refreshes_list(ui):
    page, _app, _root = ui
    task = create_task(page, "确认后删除的待办")
    tasks_page(page)

    dialog = open_dialog_from_row(page, "确认后删除的待办")
    dialog.get_by_role("button", name="删除待办", exact=True).click()

    expect(dialog).to_be_hidden()
    expect(page.locator("#tasks-toast")).to_contain_text("已删除待办")
    expect(row(page, "确认后删除的待办")).to_have_count(0)
    assert task["id"] not in task_ids(page)
    # 删除完成后焦点回到列表主操作，不落在 body
    expect(page.locator("#btn-new-task")).to_be_focused()


def test_detail_header_delete_opens_same_dialog(ui):
    page, _app, _root = ui
    task = create_task(page, "详情页删除的待办")
    tasks_page(page)
    row(page, "详情页删除的待办").locator(".task-detail-link").click()
    expect(page.locator(".tasks-scope #view-detail")).to_be_visible()

    page.locator("#btn-delete-top").click()
    dialog = page.locator(DIALOG)
    expect(dialog).to_be_visible()
    expect(dialog.locator("#delete-task-name")).to_have_text("详情页删除的待办")
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".tasks-scope #view-detail")).to_be_visible()

    page.locator("#btn-delete-top").click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="删除待办", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.locator(".tasks-scope #view-detail")).to_be_hidden()
    expect(page.locator(".tasks-scope #view-list")).to_be_visible()
    assert task["id"] not in task_ids(page)


def test_delete_failure_keeps_dialog_and_task(ui):
    page, _app, _root = ui
    task = create_task(page, "删除失败要保留")
    tasks_page(page)

    def fail_delete(route):
        if route.request.method == "DELETE":
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error":{"code":"internal_error","message":"服务器开小差了"}}',
            )
        else:
            route.continue_()

    page.route("**/api/v1/tasks/*", fail_delete)
    try:
        dialog = open_dialog_from_row(page, "删除失败要保留")
        dialog.get_by_role("button", name="删除待办", exact=True).click()
        expect(dialog.locator("#delete-task-error")).to_be_visible()
        expect(dialog.locator("#delete-task-error")).to_contain_text("服务器开小差了")
        expect(dialog).to_be_visible()
        assert task["id"] in task_ids(page)
        expect(dialog.get_by_role("button", name="删除待办", exact=True)).to_be_enabled()
    finally:
        page.unroute("**/api/v1/tasks/*", fail_delete)


def test_dialog_fits_390_viewport(ui):
    page, _app, _root = ui
    create_task(page, "手机上的删除确认")
    page.set_viewport_size({"width": 390, "height": 844})
    tasks_page(page)

    dialog = open_dialog_from_row(page, "手机上的删除确认")
    box = dialog.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390 + 0.5, box
    assert box["y"] >= 0 and box["y"] + box["height"] <= 844 + 0.5, box
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    opacity = page.locator(".tasks-scope .task-row", has_text="手机上的删除确认").locator(
        ".task-row-delete"
    ).evaluate("el => getComputedStyle(el).opacity")
    assert float(opacity) >= 0.7
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(dialog).to_be_hidden()
