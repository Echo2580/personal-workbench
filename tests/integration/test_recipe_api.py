import time
from fastapi.testclient import TestClient
from app.main import create_app


def client(tmp_path):
    c = TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1:17843")
    c.__enter__()
    token = c.get("/api/v1/bootstrap").json()["token"]
    c.headers.update({"X-Workbench-Token": token, "Origin": "http://127.0.0.1:17843"})
    return c


def test_manual_override_conflict_reset_and_approval(tmp_path):
    p = tmp_path / "章节 中文"
    p.mkdir()
    c = client(tmp_path)
    try:
        project = c.post(
            "/api/v1/projects/manual", json={"path": str(p), "name": "自定义"}
        ).json()
        pid = project["id"]
        d = c.get(f"/api/v1/projects/{pid}/recipes").json()
        draft = {
            "recipes": [
                {
                    "id": "x",
                    "label": "测试命令",
                    "kind": "command",
                    "cwd": str(p),
                    "shell_command": "echo hello",
                }
            ],
            "primary_recipe_id": "x",
        }
        h = {"If-Match": d["revision"]}
        saved = c.put(f"/api/v1/projects/{pid}/recipes", json=draft, headers=h)
        assert saved.status_code == 200, saved.text
        assert (
            c.put(f"/api/v1/projects/{pid}/recipes", json=draft, headers=h).status_code
            == 409
        )
        c.post("/api/v1/projects/scan")
        for _ in range(100):
            if not c.get("/api/v1/projects").json()["is_scanning"]:
                break
            time.sleep(0.02)
        assert c.get(f"/api/v1/projects/{pid}/recipes").json()["source"] == "manual"
        assert (
            c.post(
                f"/api/v1/projects/{pid}/recipe-approval",
                json={"recipe_id": "x", "fingerprint": "stale"},
            ).status_code
            == 409
        )
        revision = saved.json()["revision"]
        reset = c.delete(
            f"/api/v1/projects/{pid}/override", headers={"If-Match": revision}
        )
        assert reset.status_code == 200
        assert reset.json()["primary_recipe_id"] == "open-directory"
        assert c.get("/api/v1/projects").json()["projects"][0]["manual"]
    finally:
        c.__exit__(None, None, None)


def test_external_config_damage_preserves_snapshot_and_stops(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    c = client(tmp_path)
    try:
        project = c.post("/api/v1/projects/manual", json={"path": str(p)}).json()
        (tmp_path / "data" / "projects.toml").write_text("bad = [", encoding="utf-8")
        snapshot = c.get("/api/v1/projects").json()
        assert snapshot["projects"][0]["id"] == project["id"] and snapshot["warnings"]
        assert c.get("/api/v1/projects/runs").status_code == 200
        assert (
            c.put(
                f"/api/v1/projects/{project['id']}/recipes",
                json={
                    "recipes": project["recipes"],
                    "primary_recipe_id": project["primary_recipe_id"],
                },
                headers={"If-Match": "old"},
            ).status_code
            == 409
        )
    finally:
        c.__exit__(None, None, None)


def test_schema_damage_is_repairable_error_not_internal_failure(tmp_path):
    c = client(tmp_path)
    try:
        (tmp_path / "data" / "settings.toml").write_text("roots = 7", encoding="utf-8")
        response = c.get("/api/v1/settings/projects")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invalid_config"
    finally:
        c.__exit__(None, None, None)
