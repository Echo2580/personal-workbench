import sys
from concurrent.futures import ThreadPoolExecutor
from app.modules.projects.runtime import RuntimeManager
from app.modules.projects.models import Recipe, DetectedProject


def test_concurrent_start_creates_one_run(tmp_path):
    r = Recipe(
        id="x",
        label="x",
        kind="command",
        cwd=str(tmp_path),
        program=sys.executable,
        args=["-c", "import time;time.sleep(60)"],
    )
    p = DetectedProject(
        id="one",
        name="one",
        path=str(tmp_path),
        type="python",
        recipes=[r],
        primary_recipe_id="x",
    )
    m = RuntimeManager(tmp_path / "data", "test")
    try:

        def launch(_):
            try:
                return m.launch(p, r)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(launch, range(2)))
        assert sum(x is not None for x in results) == 1
        assert m.active_count() == 1
        assert not m.stop_all()["failed"]
    finally:
        m.close()
