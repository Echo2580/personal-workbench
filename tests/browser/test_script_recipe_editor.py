import pytest
from playwright.sync_api import expect


def test_visible_custom_command_entry_save_and_confirmation(ui):
    page, app, _root = ui
    page.goto(page.url.split("#")[0] + "#/projects")
    page.get_by_role("button", name="新增自定义命令", exact=True).click()
    dialog = page.get_by_role("dialog", name="编辑配方")
    recipe = dialog.locator("fieldset").last
    dialog.get_by_role("button", name="保存配方", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("请填写自定义命令")
    recipe.get_by_label("Windows CMD 命令", exact=True).fill("echo CMD")
    recipe.get_by_label("命令方式").select_option("powershell")
    recipe = dialog.locator("fieldset").last
    expect(recipe.get_by_label("Windows PowerShell 命令", exact=True)).to_have_value(
        "echo CMD"
    )
    source = "$x='中文 空格'\n$x | Write-Output\nexit 7"
    recipe.get_by_label("Windows PowerShell 命令", exact=True).fill(source)
    recipe.get_by_label("配方名称").fill("我的 PowerShell")
    recipe.get_by_role("radio", name="主配方").check()
    dialog.get_by_role("button", name="保存配方", exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role("button", name="编辑配方", exact=True).click()
    expect(page.get_by_label("Windows PowerShell 命令", exact=True)).to_have_value(
        source
    )
    page.get_by_role("button", name="取消", exact=True).click()
    page.get_by_role("button", name="启动项目", exact=True).click()
    confirm = page.get_by_role("dialog", name="确认配方")
    confirm.get_by_role("button", name="取消", exact=True).click()
    assert not app.state.projects.runtime.list_runs()
    page.get_by_role("button", name="启动项目", exact=True).click()
    confirm = page.get_by_role("dialog", name="确认配方")
    expect(confirm).to_contain_text("Windows PowerShell 命令")
    expect(confirm).to_contain_text(source)
    confirm.get_by_text("实际启动命令", exact=True).click()
    expect(confirm.locator("details")).to_contain_text("-EncodedCommand")
    confirm.get_by_role("button", name="确认并执行").click()
    expect(confirm).not_to_be_visible()
    expect(page.locator(".launch-diagnostics")).to_contain_text(
        "退出码：7", timeout=15000
    )
    expect(page.locator(".launch-diagnostics")).to_contain_text(
        "Windows PowerShell 命令"
    )
    expect(page.locator(".launch-diagnostics")).to_contain_text("执行策略")


@pytest.mark.parametrize("size", [(1440, 900), (390, 700), (900, 400)])
def test_script_candidate_parameters_primary_and_drawer_layout(ui, size):
    page, app, root = ui
    script = root / "项目 Alpha" / "启动 中文.py"
    script.write_text("raise SystemExit(7)", encoding="utf-8")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(page.url.split("#")[0] + "#/projects")
    page.get_by_role("button", name="新增运行脚本", exact=True).click()
    dialog = page.get_by_role("dialog", name="编辑配方")
    recipe = dialog.locator("fieldset").last
    recipe.get_by_role("button", name="查看项目内脚本").click()
    recipe.get_by_label("项目内脚本候选").select_option("启动 中文.py")
    recipe = dialog.locator("fieldset").last
    expect(recipe.get_by_label("脚本路径", exact=True)).to_have_value("启动 中文.py")
    recipe.get_by_label("参数（每行一项）", exact=True).fill('中文 空格\na"b')
    recipe.get_by_role("radio", name="主配方").check()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    save = dialog.get_by_role("button", name="保存配方", exact=True)
    box = save.bounding_box()
    assert box and box["y"] >= 0 and box["y"] + box["height"] <= size[1]
    page.screenshot(path=str(root.parent / f"script-editor-{size[0]}x{size[1]}.png"))
    save.click()
    expect(dialog).not_to_be_visible()
    assert not app.state.projects.runtime.list_runs(), "选择和保存脚本不能自动运行"
    page.get_by_role("button", name="编辑配方", exact=True).click()
    dialog = page.get_by_role("dialog", name="编辑配方")
    recipe = dialog.locator("fieldset").last
    expect(recipe.get_by_label("脚本路径", exact=True)).to_have_value(str(script))
    expect(recipe.get_by_label("参数（每行一项）", exact=True)).to_have_value(
        '中文 空格\na"b'
    )
    expect(recipe.get_by_role("radio", name="主配方")).to_be_checked()
    recipe.get_by_label("脚本路径", exact=True).fill("missing.py")
    dialog.get_by_role("button", name="保存配方", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("脚本必须")
    page.once("dialog", lambda d: d.accept())
    dialog.get_by_role("button", name="取消", exact=True).click()
    page.get_by_role("button", name="启动项目", exact=True).click()
    confirm = page.get_by_role("dialog", name="确认配方")
    expect(confirm).to_contain_text("Python 脚本")
    expect(confirm).to_contain_text("启动 中文.py")
    confirm.get_by_role("button", name="确认并执行").click()
    expect(confirm).not_to_be_visible()
    expect(page.locator(".launch-diagnostics")).to_contain_text(
        "退出码：7", timeout=15000
    )
