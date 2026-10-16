import time
from app.modules.projects.service import ProjectService
from app.modules.projects.models import ProjectSettings


def test_new_supported_project_appears_without_manual_scan(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    service = ProjectService(tmp_path / "data", "test")
    doc = service.get_settings()
    service.save_settings(
        ProjectSettings(roots=[str(root)], scan_interval_seconds=5), doc["revision"]
    )
    service.start()
    try:
        deadline = time.monotonic() + 3
        while service.is_scanning and time.monotonic() < deadline:
            time.sleep(0.02)
        new = root / "new"
        new.mkdir()
        (new / "index.html").write_text("<h1>fixture</h1>")
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if any(p["name"] == "new" for p in service.snapshot()["projects"]):
                break
            time.sleep(0.1)
        assert any(p["name"] == "new" for p in service.snapshot()["projects"])
    finally:
        service.close()
