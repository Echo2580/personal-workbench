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


def test_weak_root_detection_still_scans_child_projects(tmp_path):
    # 扫描根只有弱证据（顶层 html）时不能吞掉子项目。
    make(tmp_path, "index.html", "<h1>root</h1>")
    make(tmp_path / "svc", "go.mod", "module example.com/svc\n")
    make(tmp_path / "svc", "main.go", "package main\n\nfunc main() {}\n")
    make(
        tmp_path / "app",
        "package.json",
        json.dumps({"scripts": {"dev": "vite"}}),
    )
    settings = ProjectSettings(roots=[str(tmp_path)])
    result = scan_roots(settings, [])
    by_name = {Path(p.path).name: p for p in result.projects}
    assert tmp_path.name in by_name
    assert by_name[tmp_path.name].type == "web"
    assert by_name["svc"].type == "go"
    assert by_name["app"].type == "node"
    assert len(result.projects) == 3


def test_requirements_root_stays_a_project_boundary(tmp_path):
    # requirements+README 视为包项目边界：不展开其 tests/.planning 等内部目录（避免项目列表爆炸）。
    make(tmp_path, "README.md", "说明")
    make(tmp_path, "requirements.txt", "requests")
    make(tmp_path / "svc", "go.mod", "module example.com/svc\n")
    make(tmp_path / "svc", "main.go", "package main\n\nfunc main() {}\n")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert {Path(p.path).name for p in result.projects} == {tmp_path.name}


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


def test_go_rust_single_html_requirements_and_manifestless_node(tmp_path):
    make(tmp_path / "goapp", "go.mod", "module example.com/demo\n")
    make(tmp_path / "goapp", "main.go", "package main\n")
    make(tmp_path / "goapp" / "internal" / "panel", "index.html", "panel")
    make(tmp_path / "rustapp", "Cargo.toml", "[package]\nname = 'demo'\n")
    make(tmp_path / "rustapp" / "src", "main.rs", "fn main() {}\n")
    make(tmp_path / "原型", "personal-workbench_home.html", "<h1>x</h1>")
    make(tmp_path / "章节", "requirements.txt", "requests\n")
    make(tmp_path / "章节", "README.md", "运行 python -m app")
    make(tmp_path / "nodeapp", "server.mjs", "")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    by_name = {Path(p.path).name: p for p in result.projects}
    assert set(by_name) == {"goapp", "rustapp", "原型", "章节", "nodeapp"}
    assert by_name["goapp"].type == "go"
    assert by_name["rustapp"].type == "rust"
    assert by_name["原型"].type == "web"
    assert by_name["章节"].type == "python"
    assert by_name["nodeapp"].type == "node"
    assert by_name["goapp"].primary_recipe_id == "run-go"
    assert by_name["rustapp"].primary_recipe_id == "run-rust"
    assert by_name["原型"].primary_recipe_id == "open-web"
    assert by_name["nodeapp"].primary_recipe_id == "run-node"
    all_paths = [Path(p.path) for p in result.projects]
    assert all_paths.count(Path(tmp_path / "goapp")) == 1


def test_script_with_main_guard_without_readme_is_discovered(tmp_path):
    make(
        tmp_path / "工具",
        "clean.py",
        "if __name__ == '__main__':\n    print('clean')\n",
    )
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert [p.name for p in result.projects] == ["工具"]
    project = result.projects[0]
    assert project.type == "python"
    assert project.primary_recipe_id == "run-python"


def test_binaries_and_test_directories_do_not_become_projects(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool.exe").write_bytes(b"MZ\x00\x00binary")
    (tmp_path / "bin" / "data.bin").write_bytes(b"\x00\x01\x02")
    make(tmp_path / "tests", "conftest.py", "if __name__ == '__main__': pass\n")
    make(tmp_path / "tests", "test_tool.py", "if __name__ == '__main__': pass\n")
    make(tmp_path / "tests", "helper.js", "")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert result.projects == []
