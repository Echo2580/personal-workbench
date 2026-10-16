from pathlib import Path
from fastapi import APIRouter
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.contracts import ModuleDefinition, ModuleSummary


def test_new_module_has_router_menu_home_and_settings_contract(tmp_path):
    before = {p: p.read_bytes() for p in Path("app/modules/projects").glob("*.py")}
    router = APIRouter()

    @router.get("/api/v1/test-notes")
    def notes():
        return {"items": []}

    definition = ModuleDefinition(
        "notes",
        "测试笔记",
        "仅在测试登记",
        "code",
        "/notes",
        "available",
        router=router,
        summary_provider=lambda: ModuleSummary(metrics=[{"label": "笔记", "value": 0}]),
        settings_route="/settings",
    )
    app = create_app(tmp_path, extra_modules=[definition])
    with TestClient(app, base_url="http://127.0.0.1:17843") as c:
        b = c.get("/api/v1/bootstrap").json()
        m = next(m for m in b["modules"] if m["id"] == "notes")
        assert (
            m["route"] == "/notes"
            and m["settings_route"] == "/settings"
            and m["summary"]["metrics"][0]["value"] == 0
        )
        assert c.get(
            "/api/v1/test-notes", headers={"X-Workbench-Token": b["token"]}
        ).json() == {"items": []}
    assert all(p.read_bytes() == data for p, data in before.items())
