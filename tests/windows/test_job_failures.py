import sys, time
import pytest, psutil, win32process, win32job
from app.modules.projects.windows_job import WindowsJob
from app.modules.projects.models import Recipe


@pytest.mark.parametrize("phase", ["create", "assign", "resume"])
def test_failed_start_never_leaves_suspended_process(tmp_path, monkeypatch, phase):
    created = []
    original = win32process.CreateProcess

    def create(*a, **kw):
        result = original(*a, **kw)
        created.append(result[2])
        return result

    def fail(*a, **kw):
        raise OSError("injected " + phase)

    monkeypatch.setattr(
        win32process, "CreateProcess", fail if phase == "create" else create
    )
    if phase == "assign":
        monkeypatch.setattr(win32job, "AssignProcessToJobObject", fail)
    if phase == "resume":
        monkeypatch.setattr(win32process, "ResumeThread", fail)
    r = Recipe(
        id="x",
        label="test",
        kind="command",
        cwd=str(tmp_path),
        program=sys.executable,
        args=["-c", "import time;time.sleep(60)"],
    )
    with pytest.raises(Exception):
        WindowsJob().start(r)
    for pid in created:
        deadline = time.monotonic() + 3
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not psutil.pid_exists(pid)
