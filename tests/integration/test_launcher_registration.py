import sys
from pathlib import Path

import pytest

from app.core.contracts import WorkbenchError
from app.modules.projects.models import Recipe, RecipeSet
from app.modules.projects.service import ProjectService


def application(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.py").write_text("if __name__ == '__main__': pass\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# homeplate · AI 家电保养与维修助手\n", encoding="utf-8"
    )
    return root


def test_manual_virtualenv_selection_suggests_application_root_without_saving(tmp_path):
    project = application(tmp_path / "homeplate")
    selected = project / ".venv" / "Scripts"
    selected.mkdir(parents=True)
    service = ProjectService(tmp_path / "data", "test")
    before = service.projects_path.read_bytes()
    with pytest.raises(WorkbenchError) as result:
        service.add_manual_project(str(selected))
    assert result.value.code == "project_internal_directory"
    assert str(project).casefold() in result.value.message.casefold()
    assert service.projects_path.read_bytes() == before


def test_default_metadata_name_updates_without_changing_manual_name_recipe_or_id(
    tmp_path,
):
    project = application(tmp_path / "homeplate")
    service = ProjectService(tmp_path / "data", "test")
    registered = service.add_manual_project(str(project))
    assert registered["name"] == "homeplate · AI 家电保养与维修助手"
    pid = registered["id"]
    doc = service.get_recipes(pid)
    recipe = Recipe(
        id="custom",
        label="我的启动方式",
        kind="command",
        cwd=str(project),
        program=sys.executable,
        args=["-B", "run.py"],
    )
    service.save_recipes(
        pid, RecipeSet(recipes=[recipe], primary_recipe_id="custom"), doc["revision"]
    )
    service.rename_project(pid, "保留我的名称", service.projects_revision)
    (project / "README.md").write_text("# 家电助手新版\n", encoding="utf-8")
    actual = service.project(pid)
    assert actual.id == pid
    assert actual.name == "保留我的名称"
    assert actual.default_name == "家电助手新版"
    assert actual.recipe_source == "manual"
    assert actual.recipes[0] == recipe


def test_existing_manual_registration_name_still_takes_precedence(tmp_path):
    project = application(tmp_path / "homeplate")
    service = ProjectService(tmp_path / "data", "test")
    registered = service.add_manual_project(str(project), "原先手动名称")
    assert registered["name"] == registered["default_name"] == "原先手动名称"


def test_legitimate_nested_application_is_not_silently_relocated(tmp_path):
    outer = application(tmp_path / "outer")
    inner = application(outer / "services" / "inner")
    service = ProjectService(tmp_path / "data", "test")
    result = service.add_manual_project(str(inner))
    assert Path(result["path"]) == Path(str(inner).lower())


@pytest.mark.parametrize(
    "kind", ["python-script", "node-script", "interpreter", "working-directory"]
)
def test_invalid_launch_is_reported_before_runtime_attempt(tmp_path, kind):
    project = application(tmp_path / "homeplate")
    service = ProjectService(tmp_path / "data", "test")
    registered = service.add_manual_project(str(project))
    pid = registered["id"]
    program, args = sys.executable, ["-B", "missing.py"]
    expected = "entry_missing"
    if kind == "node-script":
        # A real executable path is enough; preflight must never execute it.
        program, args = str(project / "node.exe"), ["missing.js"]
        (project / "node.exe").write_bytes(b"fixture")
    elif kind == "interpreter":
        program, args, expected = (
            str(project / "missing-python.exe"),
            ["run.py"],
            "program_missing",
        )
    cwd = project if kind != "working-directory" else project / "missing"
    if kind == "working-directory":
        cwd.mkdir()
        args, expected = ["run.py"], "invalid_cwd"
    recipe = Recipe(
        id="check",
        label="检查",
        kind="command",
        cwd=str(cwd),
        program=program,
        args=args,
    )
    service.save_recipes(
        pid,
        RecipeSet(recipes=[recipe], primary_recipe_id="check"),
        service.get_recipes(pid)["revision"],
    )
    doc = service.get_recipes(pid)
    fingerprint = doc["recipes"][0]["fingerprint"]
    service.approve(pid, "check", fingerprint)
    if kind == "working-directory":
        cwd.rmdir()

    class NeverLaunch:
        def list_runs(self):
            return []

        def launch(self, *_):
            pytest.fail("Invalid recipe reached process launch")

    service.runtime = NeverLaunch()
    with pytest.raises(WorkbenchError) as result:
        service.execute(pid, "check", fingerprint)
    assert result.value.code == expected


def test_module_and_inline_python_commands_are_not_mistaken_for_file_paths(tmp_path):
    from app.modules.projects.launch_checks import validate_launch_recipe

    for args in (["-m", "http.server"], ["-c", "print('not a script.py')"]):
        validate_launch_recipe(
            Recipe(
                id="x",
                label="x",
                kind="command",
                cwd=str(tmp_path),
                program=sys.executable,
                args=args,
            )
        )
