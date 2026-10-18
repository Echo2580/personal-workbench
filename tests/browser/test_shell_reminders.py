"""外壳层提醒：整个工作台只开一个提醒会话，切页不重复开会话，多标签复用同一会话。

覆盖三件事：
1. 首页加载后由外壳发起提醒会话，且不会重复开会话；
2. 进入待办模块页后不重复开会话（模块内轮询已交给外壳）；
3. 会话写入 localStorage 共享，第二个标签页直接复用而不是另开（避免互相 supersede）。
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
    assert len(sessions) <= 1, sessions
    shared = page.evaluate("localStorage.getItem('wb.rem.session')")
    assert shared, "提醒会话应写入 localStorage 共享"
    import json

    first_session = json.loads(shared)["sessionId"]

    # 切到待办模块页（模块内不再自己开会话）
    page.get_by_role("button", name="待办清单", exact=True).click()
    expect(page.locator(".tasks-scope #view-list")).to_be_visible()
    page.wait_for_timeout(6500)
    assert len(sessions) <= 1, sessions

    # 第二个标签页（同一浏览器上下文，共享 localStorage）直接复用会话
    second = page.context.new_page()
    second.goto(page.url.split("#")[0])
    second.wait_for_load_state("networkidle")
    second.wait_for_timeout(6500)
    reused = second.evaluate("localStorage.getItem('wb.rem.session')")
    assert json.loads(reused)["sessionId"] == first_session
    second.close()
