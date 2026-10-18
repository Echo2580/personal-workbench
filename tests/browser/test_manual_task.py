"""手动新建待办对话框的浏览器回归。

本轮改版后的口径：
- 默认「不提醒」：只填名称即可保存，不需要截止时间；
- 「提前提醒」：可手动填提前分钟数，缺截止日期/时间时弹窗内提示且不提交；
- 「指定提醒时间」：可直接设提醒时刻，不需要截止日期；空/过去时刻会被拦下；
- 三种提醒写入后任务 JSON 与列表徽标一致。
"""

import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

SHANGHAI = timezone(timedelta(hours=8))


def _fetch_tasks(page):
    return page.evaluate(
        """async () => {
          const boot = await (await fetch('/api/v1/bootstrap')).json();
          const res = await fetch('/api/v1/tasks?status=all', {
            headers: {'X-Workbench-Token': boot.token},
          });
          return (await res.json()).tasks;
        }"""
    )


def _tasks_page(page):
    page.goto(page.url.split("#")[0] + "#/tasks")
    expect(page.locator(".tasks-scope #view-list")).to_be_visible()


def _open_dialog(page):
    page.get_by_role("button", name="新建待办", exact=True).click()
    dialog = page.locator("#new-task-dialog")
    expect(dialog).to_be_visible()
    return dialog


def _row(page, title):
    return page.locator(".tasks-scope .task-row", has_text=title)


def test_default_no_reminder_and_no_deadline_time_required(ui):
    page, _app, _root = ui
    _tasks_page(page)

    dialog = _open_dialog(page)
    expect(dialog.locator("#nt-reminder-mode")).to_have_value("none")
    expect(dialog.locator("#nt-relative-fields")).to_be_hidden()
    expect(dialog.locator("#nt-manual-field")).to_be_hidden()

    dialog.locator("#nt-title").fill("今天吃大盘鸡")
    due_date = dialog.locator("#nt-date").input_value()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_date), due_date
    expect(dialog.locator("#nt-time")).to_have_value("")

    dialog.get_by_role("button", name="保存待办").click()

    expect(dialog).not_to_be_visible()
    expect(page.locator(".tasks-scope #task-list")).to_contain_text("今天吃大盘鸡")
    task = {t["title"]: t for t in _fetch_tasks(page)}["今天吃大盘鸡"]
    assert task["dueTime"]["precision"] == "date"
    assert task["dueTime"]["resolvedValue"] == due_date
    assert task["reminder"]["mode"] == "none"
    assert task["reminder"]["state"] == "not_set"
    assert task["reviewIssues"] == []
    expect(_row(page, "今天吃大盘鸡")).to_contain_text("未设置")


def test_relative_reminder_needs_deadline_and_uses_custom_minutes(ui):
    page, _app, _root = ui
    _tasks_page(page)

    dialog = _open_dialog(page)
    dialog.locator("#nt-title").fill("提前 10 分钟提醒")
    dialog.locator("#nt-reminder-mode").select_option("relative")
    expect(dialog.locator("#nt-relative-fields")).to_be_visible()
    expect(dialog.locator("#nt-manual-field")).to_be_hidden()
    dialog.locator("#nt-reminder-offset").fill("10")

    # 没填截止时间：弹窗内提示，不发请求（避免后端 422「任务字段校验失败。」）
    count_before = len(_fetch_tasks(page))
    dialog.get_by_role("button", name="保存待办").click()
    error = page.locator("#nt-error")
    expect(error).to_be_visible()
    assert "提前提醒" in error.inner_text()
    expect(dialog).to_be_visible()
    page.wait_for_timeout(200)
    assert len(_fetch_tasks(page)) == count_before

    # 补上截止日期 + 时间后保存，提醒按自定义分钟数倒推
    tomorrow = (datetime.now(SHANGHAI) + timedelta(days=1)).date().isoformat()
    dialog.locator("#nt-date").fill(tomorrow)
    dialog.locator("#nt-time").fill("18:00")
    expect(error).to_be_hidden()
    dialog.get_by_role("button", name="保存待办").click()

    expect(dialog).not_to_be_visible()
    expect(page.locator(".tasks-scope #task-list")).to_contain_text("提前 10 分钟提醒")
    task = {t["title"]: t for t in _fetch_tasks(page)}["提前 10 分钟提醒"]
    assert task["dueTime"]["precision"] == "datetime"
    assert task["reminder"]["mode"] == "relative"
    assert task["reminder"]["offsetMinutes"] == 10
    assert task["reminder"]["state"] == "scheduled"
    assert task["reminder"]["scheduledAt"] == f"{tomorrow}T17:50:00+08:00"
    expect(_row(page, "提前 10 分钟提醒")).to_contain_text("已设置")


def test_manual_reminder_time_can_be_set_without_deadline(ui):
    page, _app, _root = ui
    _tasks_page(page)

    dialog = _open_dialog(page)
    dialog.locator("#nt-title").fill("指定提醒时间")
    dialog.locator("#nt-reminder-mode").select_option("manual")
    expect(dialog.locator("#nt-manual-field")).to_be_visible()
    expect(dialog.locator("#nt-relative-fields")).to_be_hidden()

    # 空提醒时间 -> 弹窗内提示
    dialog.get_by_role("button", name="保存待办").click()
    error = page.locator("#nt-error")
    expect(error).to_be_visible()
    assert "提醒时间" in error.inner_text()

    # 过去时刻 -> 弹窗内提示
    past = (datetime.now(SHANGHAI) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    dialog.locator("#nt-reminder-at").fill(past)
    dialog.get_by_role("button", name="保存待办").click()
    expect(error).to_be_visible()
    assert "晚于现在" in error.inner_text()
    expect(dialog).to_be_visible()

    # 未来时刻 + 清空截止日期：不需要截止时间也能保存
    target = (datetime.now(SHANGHAI) + timedelta(hours=2)).replace(second=0, microsecond=0)
    target_value = target.strftime("%Y-%m-%dT%H:%M")
    dialog.locator("#nt-reminder-at").fill(target_value)
    dialog.locator("#nt-date").fill("")
    dialog.get_by_role("button", name="保存待办").click()

    expect(dialog).not_to_be_visible()
    expect(page.locator(".tasks-scope #task-list")).to_contain_text("指定提醒时间")
    task = {t["title"]: t for t in _fetch_tasks(page)}["指定提醒时间"]
    assert task["dueTime"] is None
    assert task["reminder"]["mode"] == "manual"
    assert task["reminder"]["state"] == "scheduled"
    assert task["reminder"]["scheduledAt"] == target_value + ":00+08:00"
    expect(_row(page, "指定提醒时间")).to_contain_text("已设置")
