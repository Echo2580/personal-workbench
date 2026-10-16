from app.modules.projects.detectors import detect_project
from app.modules.projects.recipes import generate_recipes
from app.modules.projects.models import ProjectSettings


def test_multiple_entries_require_choice(tmp_path):
    (tmp_path / "README.md").write_text("run", encoding="utf-8")
    for n in ["first.py", "second.py"]:
        (tmp_path / n).write_text(
            "if __name__ == '__main__': print(1)", encoding="utf-8"
        )
    d = detect_project(tmp_path, ProjectSettings())
    assert len(d.entry_candidates) == 2
    assert generate_recipes(d, ProjectSettings()).primary_recipe_id == "open-directory"


def test_python_environment_does_not_use_workbench_venv(tmp_path):
    (tmp_path / "main.py").write_text(
        "if __name__ == '__main__': print(1)", encoding="utf-8"
    )
    r = generate_recipes(
        detect_project(tmp_path, ProjectSettings()),
        ProjectSettings(default_python="C:/missing/python.exe"),
    )
    assert r.recipes[0].program == "C:/missing/python.exe"


def test_oversized_entry_is_not_read(tmp_path):
    (tmp_path / "main.py").write_bytes(b"x" * (1024 * 1024 + 1))
    warnings = []
    assert detect_project(tmp_path, ProjectSettings(), warnings) is None
    assert warnings


def test_test_runner_is_not_a_business_entry(tmp_path):
    (tmp_path / "README.md").write_text("python todo.py", encoding="utf-8")
    for name in ["todo.py", "test_todo.py"]:
        (tmp_path / name).write_text(
            "if __name__ == '__main__': print(1)", encoding="utf-8"
        )
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["todo.py"]
