import sys, time, psutil
from test_instance import launch, wait_instance, call


def test_service_crash_kills_owned_job_and_restart_marks_interrupted(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    proc = launch(tmp_path / "data", "17843:17852")
    try:
        info = wait_instance(tmp_path / "data")
        project = call(info, "/projects/manual", {"path": str(root)})
        # Native service boundary is exercised; no target source files are executed.
        recipes = call(info, f"/projects/{project['id']}/recipes")
        import json, urllib.request

        draft = {
            "recipes": [
                {
                    "id": "cmd",
                    "label": "fixture",
                    "kind": "command",
                    "cwd": str(root),
                    "program": sys.executable,
                    "args": ["-c", "import time;time.sleep(60)"],
                }
            ],
            "primary_recipe_id": "cmd",
        }
        url = f"http://127.0.0.1:{info['port']}/api/v1/projects/{project['id']}/recipes"
        req = urllib.request.Request(
            url,
            data=json.dumps(draft).encode(),
            method="PUT",
            headers={
                "Origin": f"http://127.0.0.1:{info['port']}",
                "X-Workbench-Token": info["token"],
                "If-Match": recipes["revision"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as response:
            saved = json.load(response)
        body = {"recipe_id": "cmd", "fingerprint": saved["recipes"][0]["fingerprint"]}
        call(info, f"/projects/{project['id']}/recipe-approval", body)
        run = call(info, f"/projects/{project['id']}/actions", body)["run"]
        pid = run["pid"]
        # Kill the actual service (venv launcher can have a redirector parent).
        psutil.Process(info["pid"]).terminate()
        deadline = time.monotonic() + 5
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(pid)
        proc.wait(timeout=5)
        proc = launch(tmp_path / "data", "17843:17852")
        second = wait_instance(tmp_path / "data")
        assert all(
            r["status"] not in ("launching", "running", "stopping")
            for r in call(second, "/projects/runs")["runs"]
        )
        assert any(
            r["status"] == "interrupted" for r in call(second, "/projects/runs")["runs"]
        )
        call(second, "/system/shutdown", {"confirmed_stop_running": True})
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
