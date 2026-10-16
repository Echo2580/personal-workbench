import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.projects.models import ProjectSettings
from app.core.config_files import read_json, write_json


def wait_scan(c):
    for _ in range(200):
        snapshot = c.get("/api/v1/projects").json()
        if not snapshot["is_scanning"]:
            return snapshot
        time.sleep(0.02)
    pytest.fail("scan did not finish")


def connect(data):
    c = TestClient(create_app(data), base_url="http://127.0.0.1:17843")
    c.__enter__()
    c.headers.update(
        {
            "X-Workbench-Token": c.get("/api/v1/bootstrap").json()["token"],
            "Origin": "http://127.0.0.1:17843",
        }
    )
    return c


def revision(c):
    response = c.get("/api/v1/projects/removed")
    assert response.status_code == 200, response.text
    return {"If-Match": response.json()["revision"]}


@pytest.mark.parametrize("manual", [False, True], ids=["scanned", "manual"])
def test_remove_rescan_restart_restore_preserves_files_recipes_history(
    tmp_path, manual
):
    root = tmp_path / "projects"
    root.mkdir()
    p = root / "保留源码"
    p.mkdir()
    source = p / "main.py"
    source.write_bytes(b"if __name__ == '__main__': print('untouched')")
    child = root / "frontend"
    child.mkdir()
    (child / "index.html").write_text("unchanged", encoding="utf-8")
    before = {
        str(f.relative_to(root)): f.read_bytes() for f in root.rglob("*") if f.is_file()
    }
    data = tmp_path / "data"
    c = connect(data)
    try:
        if manual:
            project = c.post(
                "/api/v1/projects/manual", json={"path": str(p), "name": "自定义名称"}
            ).json()
        else:
            d = c.get("/api/v1/settings/projects").json()
            assert (
                c.put(
                    "/api/v1/settings/projects",
                    headers={"If-Match": d["revision"]},
                    json=ProjectSettings(roots=[str(root)]).model_dump(),
                ).status_code
                == 200
            )
            projects = wait_scan(c)["projects"]
            project = next(x for x in projects if x["name"] == "保留源码")
        pid = project["id"]
        recipes = c.get(f"/api/v1/projects/{pid}/recipes").json()
        draft = {
            "recipes": [
                {
                    "id": "folder",
                    "label": "保留配方",
                    "kind": "directory",
                    "target": str(p),
                }
            ],
            "primary_recipe_id": "folder",
        }
        assert (
            c.put(
                f"/api/v1/projects/{pid}/recipes",
                headers={"If-Match": recipes["revision"]},
                json=draft,
            ).status_code
            == 200
        )
        history = [
            {
                "project_id": pid,
                "created_at": "2026-10-16T01:00:00+00:00",
                "kind": "action",
            }
        ]
        write_json(data / "history/projects.json", history)
        removed = c.delete(f"/api/v1/projects/{pid}", headers=revision(c))
        assert removed.status_code == 200, removed.text
        c.post("/api/v1/projects/scan")
        snapshot = wait_scan(c)
        assert pid not in [x["id"] for x in snapshot["projects"]]
        if not manual:
            assert any(x["name"] == "frontend" for x in snapshot["projects"])
        summary = c.app.state.projects.summary()
        assert not any(x["params"]["project"] == pid for x in summary["recent_links"])
        assert summary["metrics"][0]["value"] == len(snapshot["projects"])
        assert c.get(f"/api/v1/projects/{pid}/recipes").status_code == 404
        assert (
            c.post("/api/v1/projects/manual", json={"path": str(p)}).json()["error"][
                "code"
            ]
            == "project_removed"
        )
    finally:
        c.__exit__(None, None, None)
    c = connect(data)
    try:
        assert pid not in [x["id"] for x in wait_scan(c)["projects"]]
        removed = c.get("/api/v1/projects/removed").json()
        assert removed["projects"][0]["id"] == pid
        assert removed["projects"][0]["name"] == project["name"]
        assert (
            c.post(
                f"/api/v1/projects/{pid}/restore",
                headers={"If-Match": removed["revision"]},
            ).status_code
            == 200
        )
        restored = next(x for x in wait_scan(c)["projects"] if x["id"] == pid)
        assert restored["name"] == project["name"]
        assert restored["recipe_source"] == "manual"
        assert restored["recipes"][0]["label"] == "保留配方"
        assert restored["last_action_at"] == "2026-10-16T01:00:00+00:00"
        assert c.get("/api/v1/projects/removed").json()["projects"] == []
        assert read_json(data / "history/projects.json", []) == history
        assert before == {
            str(f.relative_to(root)): f.read_bytes()
            for f in root.rglob("*")
            if f.is_file()
        }
    finally:
        c.__exit__(None, None, None)


def test_remove_rejects_running_and_stale_writes(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    c = connect(tmp_path / "data")
    try:
        project = c.post("/api/v1/projects/manual", json={"path": str(p)}).json()
        pid = project["id"]
        doc = c.get(f"/api/v1/projects/{pid}/recipes").json()
        recipe = {
            "id": "run",
            "label": "独立测试命令",
            "kind": "command",
            "cwd": str(p),
            "program": sys.executable,
            "args": ["-B", "-c", "import time; time.sleep(60)"],
        }
        saved = c.put(
            f"/api/v1/projects/{pid}/recipes",
            json={"recipes": [recipe], "primary_recipe_id": "run"},
            headers={"If-Match": doc["revision"]},
        ).json()
        action = {"recipe_id": "run", "fingerprint": saved["recipes"][0]["fingerprint"]}
        assert (
            c.post(f"/api/v1/projects/{pid}/recipe-approval", json=action).status_code
            == 200
        )
        started = c.post(f"/api/v1/projects/{pid}/actions", json=action)
        assert started.status_code == 202, started.text
        run = started.json()["run"]
        rejected = c.delete(f"/api/v1/projects/{pid}", headers=revision(c))
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "project_running"
        assert c.get("/api/v1/projects/removed").json()["projects"] == []
        assert (
            c.post(f"/api/v1/projects/runs/{run['id']}/stop").json()["status"]
            == "stopped"
        )
        stale = revision(c)
        assert c.delete(f"/api/v1/projects/{pid}", headers=stale).status_code == 200
        removed_revision = revision(c)
        assert (
            c.post(f"/api/v1/projects/{pid}/restore", headers=stale).status_code == 409
        )
        assert c.get("/api/v1/projects").json()["projects"] == []
        assert (
            c.post(f"/api/v1/projects/{pid}/restore", headers=revision(c)).status_code
            == 200
        )
        assert (
            c.delete(f"/api/v1/projects/{pid}", headers=removed_revision).status_code
            == 409
        )
        assert c.get("/api/v1/projects").json()["projects"][0]["id"] == pid
    finally:
        c.__exit__(None, None, None)
