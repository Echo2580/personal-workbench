from playwright.sync_api import expect


def test_rename_cancel_save_search_reload_and_reset(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="修改名称", exact=True).click()
    dialog = page.get_by_role("dialog", name="修改项目名称")
    dialog.get_by_label("项目名称", exact=True).fill("取消的名字")
    dialog.get_by_role("button", name="取消", exact=True).click()
    expect(page.get_by_role("heading", name="项目 Alpha", exact=True)).to_be_visible()
    page.get_by_role("button", name="修改名称", exact=True).click()
    dialog.get_by_label("项目名称", exact=True).fill(" ")
    dialog.get_by_role("button", name="保存名称", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("不能为空")
    dialog.get_by_label("项目名称", exact=True).fill("我的开发服务")
    dialog.get_by_label("项目名称", exact=True).press("Enter")
    expect(page.get_by_role("heading", name="我的开发服务", exact=True)).to_be_visible()
    search = page.get_by_role("searchbox", name="搜索项目")
    search.fill("我的开发")
    expect(page.get_by_role("heading", name="我的开发服务", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="我的开发服务", exact=True)).to_be_visible()
    page.get_by_role("button", name="修改名称", exact=True).click()
    dialog.get_by_role("button", name="恢复默认名称", exact=True).click()
    expect(page.get_by_role("heading", name="项目 Alpha", exact=True)).to_be_visible()
    assert (root / "项目 Alpha" / "main.py").is_file()


def test_name_conflict_keeps_input_during_poll(ui):
    page, app, root = ui
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="修改名称", exact=True).click()
    dialog = page.get_by_role("dialog", name="修改项目名称")
    dialog.get_by_label("项目名称", exact=True).fill("保留的名称草稿")
    path = app.state.projects.projects_path
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# external update\n", encoding="utf-8"
    )
    page.wait_for_timeout(2400)
    dialog.get_by_role("button", name="保存名称", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("配置已被")
    expect(dialog.get_by_label("项目名称", exact=True)).to_have_value("保留的名称草稿")


def test_old_backend_explains_rename_requires_restart(ui):
    page, app, root = ui

    def old_projects(route):
        response = route.fetch()
        data = response.json()
        data.pop("capabilities", None)
        route.fulfill(response=response, json=data)

    page.route("**/api/v1/projects", old_projects)
    page.get_by_role("button", name="进入项目启动器").click()
    page.get_by_role("button", name="修改名称", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="需要重启工作台")).to_be_visible()
    expect(page.get_by_role("dialog", name="修改项目名称")).to_have_count(0)
