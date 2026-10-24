import hashlib
import json

import pytest

from app.core.contracts import WorkbenchError
from app.modules.projects.models import ProjectSettings, Recipe
from app.modules.projects.recipes import recipe_fingerprint
from app.modules.projects.scripts import discover_scripts, validate_script_path


def test_script_discovery_is_bounded_read_only_and_excludes_dependencies(tmp_path):
    for name in [
        "启动.cmd",
        "scripts/部署.ps1",
        "bin/run.bat",
        "tools/check.py",
        "node_modules/bad.py",
        ".venv/skip.py",
        "src/hidden.py",
        "scripts/deep/hidden.py",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must never run", encoding="utf-8")
    result = discover_scripts(tmp_path, ProjectSettings())
    assert set(result["candidates"]) == {
        "启动.cmd",
        r"scripts\部署.ps1",
        r"bin\run.bat",
        r"tools\check.py",
    }
    assert not result["limited"]
    for i in range(110):
        (tmp_path / f"{i}.py").touch()
    result = discover_scripts(tmp_path, ProjectSettings())
    assert result["limited"] and len(result["candidates"]) <= 100


@pytest.mark.parametrize(
    "target", ["../outside.py", ".venv/skip.py", "missing.ps1", "readme.txt"]
)
def test_script_paths_reject_escape_dependencies_missing_and_other_files(
    tmp_path, target
):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/skip.py").touch()
    (tmp_path / "readme.txt").touch()
    with pytest.raises(WorkbenchError, match="脚本必须"):
        validate_script_path(tmp_path, target)


def test_old_cmd_and_native_fingerprints_are_unchanged():
    for fields in [
        {"shell_command": "echo hello"},
        {"program": "python", "args": ["main.py"]},
    ]:
        recipe = Recipe(id="r", label="r", kind="command", cwd="C:\\project", **fields)
        old = recipe.model_dump(exclude={"shell"})
        fingerprint = hashlib.sha256(
            json.dumps(
                {"project_id": "p", **old},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        assert recipe_fingerprint("p", recipe) == fingerprint
    ps = recipe.model_copy(
        update={
            "program": None,
            "args": [],
            "shell_command": "echo hello",
            "shell": "powershell",
        }
    )
    assert recipe_fingerprint("p", ps) != recipe_fingerprint(
        "p", ps.model_copy(update={"shell": "cmd"})
    )
