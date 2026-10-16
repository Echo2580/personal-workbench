from app.core.contracts import ModuleDefinition
from playwright.sync_api import expect


def test_extra_module_appears_in_navigation_home_route_and_settings(ui):
    page, app, root = ui
    app.state.registry.register(
        ModuleDefinition(
            "notes",
            "测试笔记",
            "仅测试使用",
            "code",
            "/notes",
            "available",
            settings_route="/settings",
        )
    )

    def loader(route):
        response = route.fetch()
        route.fulfill(
            response=response,
            body=response.text()
            + "\nmoduleLoaders.notes=async()=>({mountPage:c=>{c.textContent='笔记测试页面';},mountSettings:c=>{c.textContent='笔记测试设置';}});",
        )

    page.route("**/core/module-loaders.js", loader)
    page.reload()
    page.get_by_role("button", name="进入测试笔记").click()
    expect(page.get_by_text("笔记测试页面", exact=True)).to_be_visible()
    page.get_by_role("button", name="设置", exact=True).click()
    expect(page.get_by_text("笔记测试设置", exact=True)).to_be_visible()
