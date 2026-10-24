from test_recipe_api import client
from app.modules.projects.service import ProjectService


def put(c, pid, doc, recipes, primary):
    response = c.put(
        f"/api/v1/projects/{pid}/recipes",
        json={"recipes": recipes, "primary_recipe_id": primary},
        headers={"If-Match": doc["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_script_save_reload_interpreter_confirm_lock_and_stop(tmp_path):
    root = tmp_path / "中文 项目"
    root.mkdir()
    script = root / "临时.py"
    script.write_text("import time;time.sleep(60)", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts/read.ps1").write_text("throw 'never run'")
    c = client(tmp_path)
    try:
        pid = c.post("/api/v1/projects/manual", json={"path": str(root)}).json()["id"]
        candidates = c.get(f"/api/v1/projects/{pid}/scripts").json()
        assert set(candidates["candidates"]) == {"临时.py", r"scripts\read.ps1"}
        doc = c.get(f"/api/v1/projects/{pid}/recipes").json()
        recipe = dict(
            id="script",
            label="运行脚本",
            kind="script",
            target="临时.py",
            cwd=str(root),
            args=["中文 空格", 'a"b'],
        )
        saved = put(c, pid, doc, [recipe], "script")
        row = saved["recipes"][0]
        assert row["target"] == str(script)
        assert row["program"].lower().endswith("python.exe")
        reloaded = ProjectService(tmp_path / "data", "reload").get_recipes(pid)
        assert reloaded["recipes"] == saved["recipes"]
        action = dict(recipe_id="script", fingerprint=row["fingerprint"])
        assert (
            c.post(f"/api/v1/projects/{pid}/actions", json=action).json()["error"][
                "code"
            ]
            == "approval_required"
        )
        assert (
            c.post(f"/api/v1/projects/{pid}/recipe-approval", json=action).status_code
            == 200
        )
        launched = c.post(f"/api/v1/projects/{pid}/actions", json=action)
        assert launched.status_code == 202, launched.text
        run = launched.json()["run"]
        assert str(script) in run["execution"]["command_line"]
        assert (
            c.post(f"/api/v1/projects/{pid}/actions", json=action).json()["error"][
                "code"
            ]
            == "already_running"
        )
        recipe["args"] = ["changed"]
        assert (
            c.put(
                f"/api/v1/projects/{pid}/recipes",
                json={"recipes": [recipe], "primary_recipe_id": "script"},
                headers={"If-Match": saved["revision"]},
            ).json()["error"]["code"]
            == "running_recipe_locked"
        )
        assert (
            c.post(f"/api/v1/projects/runs/{run['id']}/stop").json()["status"]
            == "stopped"
        )
        changed = put(c, pid, saved, [recipe], "script")
        assert (
            c.post(f"/api/v1/projects/{pid}/actions", json=action).json()["error"][
                "code"
            ]
            == "recipe_changed"
        )
        action["fingerprint"] = changed["recipes"][0]["fingerprint"]
        assert (
            c.post(f"/api/v1/projects/{pid}/actions", json=action).json()["error"][
                "code"
            ]
            == "approval_required"
        )
        script.unlink()
        assert (
            c.put(
                f"/api/v1/projects/{pid}/recipes",
                json={"recipes": [recipe], "primary_recipe_id": "script"},
                headers={"If-Match": changed["revision"]},
            ).status_code
            == 422
        )
    finally:
        c.__exit__(None, None, None)


def test_shell_change_requires_confirmation_and_saves_multiline(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    c = client(tmp_path)
    try:
        pid = c.post("/api/v1/projects/manual", json={"path": str(root)}).json()["id"]
        doc = c.get(f"/api/v1/projects/{pid}/recipes").json()
        recipe = dict(
            id="r",
            label="自定义",
            kind="command",
            cwd=str(root),
            shell_command="echo hello",
        )
        saved = put(c, pid, doc, [recipe], "r")
        action = dict(recipe_id="r", fingerprint=saved["recipes"][0]["fingerprint"])
        c.post(f"/api/v1/projects/{pid}/recipe-approval", json=action)
        recipe.update(
            shell="powershell", shell_command="$x='中文'\n$x | Write-Output\nexit 7"
        )
        changed = put(c, pid, saved, [recipe], "r")
        assert changed["recipes"][0]["shell_command"] == recipe["shell_command"]
        assert "-EncodedCommand" in changed["execution"]["r"]["command_line"]
        assert (
            c.post(f"/api/v1/projects/{pid}/actions", json=action).json()["error"][
                "code"
            ]
            == "recipe_changed"
        )
        action["fingerprint"] = changed["recipes"][0]["fingerprint"]
        assert (
            c.post(f"/api/v1/projects/{pid}/actions", json=action).json()["error"][
                "code"
            ]
            == "approval_required"
        )
    finally:
        c.__exit__(None, None, None)
