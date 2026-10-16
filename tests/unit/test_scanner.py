import json
from pathlib import Path
from app.modules.projects.scanner import scan_roots, project_id
from app.modules.projects.models import ProjectSettings


def make(p, name, text):
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(text, encoding="utf-8")


def test_independent_front_back_and_hidden_children(tmp_path):
    make(
        tmp_path / "前后端" / "frontend",
        "package.json",
        json.dumps({"scripts": {"dev": "vite"}}),
    )
    make(
        tmp_path / "前后端" / "backend",
        "package.json",
        json.dumps({"scripts": {"start": "node index.js"}}),
    )
    make(tmp_path / "game", "main.py", "if __name__ == '__main__': print('x')")
    make(tmp_path / "game" / "persona", "index.html", "x")
    make(tmp_path / "todo", "README.md", "运行 todo.py")
    make(tmp_path / "todo", "todo.py", "if __name__ == '__main__': print('x')")
    make(tmp_path / "web", "index.html", "<h1>x</h1>")
    make(tmp_path / "coverage", "index.html", "x")
    make(tmp_path / "chapter", "requirements.txt", "requests")
    make(tmp_path / "chapter", "exercise.py", "print(1)")
    settings = ProjectSettings(roots=[str(tmp_path), str(tmp_path / "game")])
    result = scan_roots(settings, [])
    assert {Path(p.path).name for p in result.projects} == {
        "frontend",
        "backend",
        "game",
        "todo",
        "web",
    }
    assert len(result.projects) == 5
    assert project_id(tmp_path / "game") == project_id(str(tmp_path / "game").upper())


def test_limits_bad_file_and_missing_root(tmp_path):
    make(tmp_path / "bad", "package.json", "{")
    make(tmp_path / "ok", "index.html", "x")
    r = scan_roots(
        ProjectSettings(
            roots=[str(tmp_path), str(tmp_path / "gone")], max_directories=1
        ),
        [],
    )
    assert r.limited and r.warnings
    assert r.root_states[str(tmp_path / "gone")] == "root_unavailable"


def test_workspaces_and_junctions(tmp_path):
    make(
        tmp_path,
        "package.json",
        json.dumps({"scripts": {"dev": "node ."}, "workspaces": ["packages/*"]}),
    )
    make(
        tmp_path / "packages" / "a",
        "package.json",
        json.dumps({"scripts": {"start": "node ."}}),
    )
    r = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert len(r.projects) == 2


def test_malformed_manifest_does_not_abort_other_projects(tmp_path):
    make(tmp_path / "broken", "package.json", "[]")
    make(tmp_path / "good", "index.html", "<h1>ok</h1>")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert [p.name for p in result.projects] == ["good"]
    assert result.warnings
