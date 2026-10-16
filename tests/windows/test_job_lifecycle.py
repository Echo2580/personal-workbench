import sys, time, subprocess
import pytest
import psutil
from app.modules.projects.models import Recipe, DetectedProject
from app.modules.projects.runtime import RuntimeManager


def wait_for(condition, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    assert condition(), "等待真实进程状态超时"


def project(path):
    return DetectedProject(
        id="fixture",
        name="fixture",
        path=str(path),
        type="python",
        recipes=[
            Recipe(
                id="run",
                label="运行",
                kind="command",
                cwd=str(path),
                program=sys.executable,
                args=["-c", "import time;time.sleep(60)"],
            )
        ],
        primary_recipe_id="run",
    )


def test_parent_exits_child_remains_stop_isolated(tmp_path):
    child_pid = tmp_path / "child.txt"
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess,sys\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nopen(sys.argv[1],'w').write(str(p.pid))\n",
        encoding="utf-8",
    )
    external = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    manager = RuntimeManager(tmp_path / "data", "instance")
    try:
        p = project(tmp_path)
        r = p.recipes[0].model_copy(update={"args": [str(script), str(child_pid)]})
        run = manager.launch(p, r)
        wait_for(child_pid.exists)
        pid = int(child_pid.read_text())
        time.sleep(0.6)
        assert manager.list_runs()[0]["status"] == "running"
        with pytest.raises(Exception):
            manager.launch(p, r)
        assert manager.stop(run["id"])["status"] == "stopped"
        wait_for(lambda: not psutil.pid_exists(pid))
        assert external.poll() is None
    finally:
        manager.close()
        external.terminate()
        external.wait(timeout=5)


def test_exit_codes_and_history_not_reclaimed(tmp_path):
    manager = RuntimeManager(tmp_path, "one")
    try:
        p = project(tmp_path)
        for code, status in [(0, "exited"), (7, "failed")]:
            r = p.recipes[0].model_copy(
                update={"args": ["-c", f"raise SystemExit({code})"]}
            )
            run = manager.launch(p, r)
            wait_for(
                lambda: (
                    next(x for x in manager.list_runs() if x["id"] == run["id"])[
                        "status"
                    ]
                    == status
                )
            )
            ended = next(x for x in manager.list_runs() if x["id"] == run["id"])
            assert ended["exit_code"] == code
    finally:
        manager.close()
    restarted = RuntimeManager(tmp_path, "two")
    try:
        assert restarted.active_count() == 0
    finally:
        restarted.close()
