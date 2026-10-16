import pytest
from app.modules.projects.settings import validate_settings
from app.modules.projects.models import ProjectSettings


def test_roots_deduplicate_covered_paths(tmp_path):
    (tmp_path / "child").mkdir()
    s = validate_settings(
        ProjectSettings(
            roots=[str(tmp_path / "child"), str(tmp_path), str(tmp_path).upper()]
        )
    )
    assert len(s.roots) == 1
    with pytest.raises(Exception):
        validate_settings(ProjectSettings(roots=[str(tmp_path / "absent")]))
