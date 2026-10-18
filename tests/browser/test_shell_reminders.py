"""外壳层提醒：整个工作台只开一个提醒会话，切页不重复开会话。

覆盖两件事：
1. 首页加载后由外壳发起且仅发起一次 POST /api/v1/reminder-sessions；
2. 进入待办模块页后不重复开会话（模块内轮询已交给外壳）。
"""

from playwright.sync_api import expect


def test_shell_owns_single_reminder_session_across_pages(ui):
    page, app, _root = ui
    sessions = []

    def track(request):
        if request.method == "POST" and request.url.endswith("/reminder-sessions"):
            sessions.append(request.url)

    page.on("request", track)

    page.goto(page.url.split("#")[0])
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6500)
    assert len(sessions) == 1, sessions

    # 切到待办模块页（模块内不再自己开会话）
    page.get_by_role("button", name="待办清单", exact=True).click()
    expect(page.locator(".tasks-scope #view-list")).to_be_visible()
    page.wait_for_timeout(6500)
    assert len(sessions) == 1, sessions
