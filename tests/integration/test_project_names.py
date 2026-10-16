import sys

import pytest

from app.core.config_files import read_json, write_json
from app.modules.projects.models import ProjectSettings
from test_project_removal import connect, wait_scan


def headers(c):
    return {"If-Match": c.get("/api/v1/projects").json()["revision"]}


@pytest.mark.parametrize("manual", [False, True], ids=["scanned", "manual"])
def test_custom_name_survives_scan_restart_remove_restore_without_changing_recipe_or_files(
    tmp_path, manual
):
    root = tmp_path / "projects"
    root.mkdir()
    folder = root / "original"
    folder.mkdir()
    source = folder / "main.py"
    source.write_text("if __name__ == '__main__': print('unchanged')", encoding="utf-8")
    before = source.read_bytes()
    data = tmp_path / "data"
    c = connect(data)
    try:
        if manual:
            project = c.post(
                "/api/v1/projects/manual",
                json={"path": str(folder), "name": "最初登记名称"},
            ).json()
            default = "最初登记名称"
        else:
            doc = c.get("/api/v1/settings/projects").json()
            c.put(
                "/api/v1/settings/projects",
                headers={"If-Match": doc["revision"]},
                json=ProjectSettings(roots=[str(root)]).model_dump(),
            )
            project = wait_scan(c)["projects"][0]
            default = "original"
        pid = project["id"]
        recipes = c.get(f"/api/v1/projects/{pid}/recipes").json()
        history = [
            {
                "project_id": pid,
                "kind": "action",
                "created_at": "2026-10-16T01:00:00+00:00",
            }
        ]
        write_json(data / "history/projects.json", history)
        response = c.patch(
            f"/api/v1/projects/{pid}/name",
            json={"name": "  我的常用项目  "},
            headers=headers(c),
        )
        assert response.status_code == 200, response.text
        actual = c.get("/api/v1/projects").json()["projects"][0]
        assert actual["id"] == pid and actual["path"] == project["path"]
        assert actual["name"] == "我的常用项目"
        assert actual["default_name"] == default and actual["has_custom_name"]
        assert (
            c.app.state.projects.summary()["recent_links"][0]["label"] == "我的常用项目"
        )
        after = c.get(f"/api/v1/projects/{pid}/recipes").json()
        assert after["source"] == recipes["source"]
        assert after["recipes"] == recipes["recipes"]
        c.post("/api/v1/projects/scan")
        assert wait_scan(c)["projects"][0]["name"] == "我的常用项目"
        assert (
            c.delete(f"/api/v1/projects/{pid}", headers=headers(c)).status_code == 200
        )
        assert (
            c.get("/api/v1/projects/removed").json()["projects"][0]["name"]
            == "我的常用项目"
        )
        assert (
            c.post(f"/api/v1/projects/{pid}/restore", headers=headers(c)).status_code
            == 200
        )
    finally:
        c.__exit__(None, None, None)
    c = connect(data)
    try:
        actual = wait_scan(c)["projects"][0]
        assert actual["name"] == "我的常用项目"
        assert (
            c.delete(f"/api/v1/projects/{pid}/name", headers=headers(c)).status_code
            == 200
        )
        actual = c.get("/api/v1/projects").json()["projects"][0]
        assert actual["name"] == default and not actual["has_custom_name"]
        assert read_json(data / "history/projects.json", []) == history
        assert source.read_bytes() == before and folder.is_dir()
    finally:
        c.__exit__(None, None, None)


def test_name_rejects_invalid_input_and_preserves_other_metadata(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    c = connect(tmp_path / "data")
    try:
        p = c.post("/api/v1/projects/manual", json={"path": str(folder)}).json()
        url = f"/api/v1/projects/{p['id']}/name"
        initial = (tmp_path / "data/projects.toml").read_bytes()
        for name in ["", "  ", "a" * 121, "two\nlines", "bad\x00name"]:
            r = c.patch(url, json={"name": name}, headers=headers(c))
            assert r.status_code == 422, (repr(name), r.text)
            assert (tmp_path / "data/projects.toml").read_bytes() == initial
        assert (
            c.patch(
                url, json={"name": "合法", "path": "different"}, headers=headers(c)
            ).status_code
            == 422
        )
        assert (
            c.patch(url, json={"name": "名字"}, headers=headers(c)).status_code == 200
        )
        assert c.get("/api/v1/projects").json()["projects"][0]["name"] == "名字"
    finally:
        c.__exit__(None, None, None)


def test_stale_rename_and_reset_are_rejected(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    c = connect(tmp_path / "data")
    try:
        p = c.post("/api/v1/projects/manual", json={"path": str(folder)}).json()
        url = f"/api/v1/projects/{p['id']}/name"
        stale = headers(c)
        assert c.patch(url, json={"name": "已保存"}, headers=stale).status_code == 200
        assert c.patch(url, json={"name": "旧窗口"}, headers=stale).status_code == 409
        assert c.delete(url, headers=stale).status_code == 409
        assert c.get("/api/v1/projects").json()["projects"][0]["name"] == "已保存"
    finally:
        c.__exit__(None, None, None)


def test_rename_and_reset_running_project_keep_process_approval_and_shutdown_label(
    tmp_path,
):
    folder = tmp_path / "project"
    folder.mkdir()
    c = connect(tmp_path / "data")
    try:
        p = c.post("/api/v1/projects/manual", json={"path": str(folder)}).json()
        pid = p["id"]
        doc = c.get(f"/api/v1/projects/{pid}/recipes").json()
        draft = {
            "recipes": [
                {
                    "id": "run",
                    "label": "隔离运行",
                    "kind": "command",
                    "cwd": str(folder),
                    "program": sys.executable,
                    "args": ["-B", "-c", "import time;time.sleep(60)"],
                }
            ],
            "primary_recipe_id": "run",
        }
        saved = c.put(
            f"/api/v1/projects/{pid}/recipes",
            json=draft,
            headers={"If-Match": doc["revision"]},
        ).json()
        body = {"recipe_id": "run", "fingerprint": saved["recipes"][0]["fingerprint"]}
        c.post(f"/api/v1/projects/{pid}/recipe-approval", json=body)
        started = c.post(f"/api/v1/projects/{pid}/actions", json=body)
        assert started.status_code == 202, started.text
        run = started.json()["run"]
        url = f"/api/v1/projects/{pid}/name"
        assert (
            c.patch(
                url, json={"name": "正在运行的新名称"}, headers=headers(c)
            ).status_code
            == 200
        )
        current = c.get("/api/v1/projects").json()["projects"][0]
        assert (
            current["active_run"]["id"] == run["id"]
            and current["active_run"]["pid"] == run["pid"]
        )
        assert (
            c.get("/api/v1/system/shutdown-preview").json()["running_items"][0]["label"]
            == "正在运行的新名称"
        )
        assert (
            c.get(f"/api/v1/projects/{pid}/recipes").json()["recipes"][0]["fingerprint"]
            == body["fingerprint"]
        )
        assert c.delete(url, headers=headers(c)).status_code == 200
        assert (
            c.get("/api/v1/system/shutdown-preview").json()["running_items"][0]["label"]
            == "project"
        )
        assert (
            c.post(f"/api/v1/projects/runs/{run['id']}/stop").json()["status"]
            == "stopped"
        )
        assert c.post(f"/api/v1/projects/{pid}/actions", json=body).status_code == 202
    finally:
        c.__exit__(None, None, None)
