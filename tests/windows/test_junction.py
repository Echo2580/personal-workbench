import subprocess
from app.modules.projects.scanner import scan_roots
from app.modules.projects.models import ProjectSettings


def test_junction_is_not_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "index.html").write_text("test")
    link = root / "linked"
    # One native PowerShell operation; no file deletion through another shell.
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "New-Item -ItemType Junction -Path '"
            + str(link).replace("'", "''")
            + "' -Target '"
            + str(target).replace("'", "''")
            + "'",
        ],
        capture_output=True,
    )
    if result.returncode:
        import pytest

        pytest.skip(
            "当前环境无法创建 junction: " + result.stderr.decode(errors="replace")
        )
    assert scan_roots(ProjectSettings(roots=[str(root)]), []).projects == []
