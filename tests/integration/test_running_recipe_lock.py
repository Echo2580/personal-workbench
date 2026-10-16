import sys
from fastapi.testclient import TestClient
from app.main import create_app


def test_api_locks_running_recipe_and_allows_stopping_after_config_damage(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with TestClient(
        create_app(tmp_path / "data"), base_url="http://127.0.0.1:17843"
    ) as c:
        c.headers.update(
            {
                "X-Workbench-Token": c.get("/api/v1/bootstrap").json()["token"],
                "Origin": "http://127.0.0.1:17843",
            }
        )
        p = c.post("/api/v1/projects/manual", json={"path": str(root)}).json()
        pid = p["id"]
        doc = c.get(f"/api/v1/projects/{pid}/recipes").json()
        recipes = doc["recipes"]
        [r.pop("fingerprint") for r in recipes]
        recipes.insert(
            0,
            dict(
                id="run",
                label="run",
                kind="command",
                cwd=str(root),
                program=sys.executable,
                args=["-c", "import time;time.sleep(60)"],
            ),
        )
        saved = c.put(
            f"/api/v1/projects/{pid}/recipes",
            json={"recipes": recipes, "primary_recipe_id": "run"},
            headers={"If-Match": doc["revision"]},
        ).json()
        fingerprint = saved["recipes"][0]["fingerprint"]
        body = {"recipe_id": "run", "fingerprint": fingerprint}
        assert c.post(f"/api/v1/projects/{pid}/actions", json=body).status_code == 409
        c.post(f"/api/v1/projects/{pid}/recipe-approval", json=body)
        response = c.post(f"/api/v1/projects/{pid}/actions", json=body)
        assert response.status_code == 202
        run = response.json()["run"]
        draft = {"recipes": recipes, "primary_recipe_id": "open-directory"}
        assert (
            c.put(
                f"/api/v1/projects/{pid}/recipes",
                json=draft,
                headers={"If-Match": saved["revision"]},
            ).status_code
            == 409
        )
        recipes[-1]["label"] = "folder updated"
        assert (
            c.put(
                f"/api/v1/projects/{pid}/recipes",
                json={"recipes": recipes, "primary_recipe_id": "run"},
                headers={"If-Match": saved["revision"]},
            ).status_code
            == 200
        )
        (tmp_path / "data" / "projects.toml").write_text("bad=[", encoding="utf-8")
        assert (
            c.post(f"/api/v1/projects/runs/{run['id']}/stop").json()["status"]
            == "stopped"
        )
