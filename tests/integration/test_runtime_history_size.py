import sys, time
from app.modules.projects.models import Recipe
from app.main import create_app
from app.modules.projects.runtime import RuntimeManager


def test_project_run_history_does_not_nest_old_snapshots(tmp_path):
    app = create_app(tmp_path / "data")
    s = app.state.projects
    root = tmp_path / "project"
    root.mkdir()
    p = s.add_manual_project(root)
    m = RuntimeManager(s.data_dir, s.instance_id)
    s.runtime = m
    r = Recipe(
        id="x",
        label="x",
        kind="command",
        cwd=str(root),
        program=sys.executable,
        args=["-c", "pass"],
    )
    try:
        for _ in range(3):
            run = m.launch(s.project(p["id"]), r)
            for _ in range(100):
                if m.active_count() == 0:
                    break
                time.sleep(0.02)
            snapshot = next(x for x in m.list_runs() if x["id"] == run["id"])[
                "project_snapshot"
            ]
            assert not snapshot.get("last_run") and not snapshot.get("active_run")
    finally:
        m.close()
        s.close()
