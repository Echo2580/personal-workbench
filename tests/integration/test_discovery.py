from app.modules.projects.store import ProjectStore
from app.modules.projects.scanner import scan_roots
from app.modules.projects.models import ProjectSettings


def test_unavailable_root_keeps_previous_projects(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "index.html").write_text("x")
    store = ProjectStore(tmp_path / "data")
    store.replace_scan(scan_roots(ProjectSettings(roots=[str(root)]), []))
    root.rename(tmp_path / "moved")
    store.replace_scan(scan_roots(ProjectSettings(roots=[str(root)]), []))
    assert (
        len(store.projects) == 1
        and store.projects[0].availability == "root_unavailable"
    )
