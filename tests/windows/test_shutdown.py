import sys
import pytest
from app.main import create_app
from app.modules.projects.runtime import RuntimeManager
from app.modules.projects.models import Recipe
from app.core.shutdown import ShutdownCoordinator


def test_confirm_running_cancel_and_stop_failure(tmp_path, monkeypatch):
    app = create_app(tmp_path / "data")
    service = app.state.projects
    root = tmp_path / "project"
    root.mkdir()
    p = service.add_manual_project(root)
    runtime = RuntimeManager(service.data_dir, service.instance_id)
    service.runtime = runtime
    project = service.project(p["id"])
    recipe = Recipe(
        id="cmd",
        label="cmd",
        kind="command",
        cwd=str(root),
        program=sys.executable,
        args=["-c", "import time;time.sleep(60)"],
    )
    exited = []
    shutdown = ShutdownCoordinator(
        lock=service.lock,
        running_items=service.shutdown_items,
        stop_all=lambda: runtime.stop_all(),
        block_actions=service.block_actions,
        on_shutdown=lambda: exited.append(True),
    )
    try:
        runtime.launch(project, recipe)
        with pytest.raises(Exception) as e:
            shutdown.request(False)
        assert e.value.status == 409 and runtime.active_count() == 1 and not exited
        original = runtime.stop_all
        monkeypatch.setattr(
            runtime,
            "stop_all",
            lambda: {"stopped": [], "failed": [{"run_id": "test", "message": "失败"}]},
        )
        with pytest.raises(Exception):
            shutdown.request(True)
        assert not exited and not service.shutting_down
        monkeypatch.setattr(runtime, "stop_all", original)
        assert shutdown.request(True)["status"] == "shutting_down"
        assert runtime.active_count() == 0 and exited
    finally:
        runtime.close()
        service.close()
