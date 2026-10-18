import json
import os

import pytest

from app.modules.projects.detectors import detect_project
from app.modules.projects.recipes import generate_recipes
from app.modules.projects.models import ProjectSettings


def guard(body="print(1)"):
    return f"if __name__ == '__main__':\n    {body}\n"


def write(path, name, text):
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_multiple_entries_require_choice(tmp_path):
    write(tmp_path, "README.md", "run")
    for n in ["first.py", "second.py"]:
        write(tmp_path, n, guard())
    d = detect_project(tmp_path, ProjectSettings())
    assert len(d.entry_candidates) == 2
    assert generate_recipes(d, ProjectSettings()).primary_recipe_id == "open-directory"


def test_python_environment_does_not_use_workbench_venv(tmp_path):
    write(tmp_path, "main.py", guard())
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
    write(tmp_path, "README.md", "python todo.py")
    for name in ["todo.py", "test_todo.py"]:
        write(tmp_path, name, guard())
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["todo.py"]


def test_any_toplevel_main_guard_is_entry_without_readme_or_pyproject(tmp_path):
    write(tmp_path, "todo.py", guard())
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "python"
    assert d.entry_candidates == ["todo.py"]
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-python"
    assert r.recipes[0].args == ["todo.py"]


def test_known_entry_names_are_prioritized(tmp_path):
    for name in ["zebra.py", "run.py", "app.py", "main.py", "helper.py"]:
        write(tmp_path, name, guard())
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates[:3] == ["main.py", "app.py", "run.py"]
    assert set(d.entry_candidates) == {"zebra.py", "helper.py", "main.py", "app.py", "run.py"}


def test_test_setup_and_conftest_files_are_not_entries(tmp_path):
    for name in ["setup.py", "conftest.py", "test_demo.py", "demo_test.py"]:
        write(tmp_path, name, guard())
    write(tmp_path, "tool.py", guard())
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["tool.py"]


def test_only_excluded_python_files_is_not_a_project(tmp_path):
    write(tmp_path, "setup.py", guard())
    write(tmp_path, "conftest.py", guard())
    assert detect_project(tmp_path, ProjectSettings()) is None


def test_symlinked_entry_is_not_read(tmp_path):
    real = tmp_path.parent / "outside_entry.py"
    real.write_text(guard(), encoding="utf-8")
    write(tmp_path, "helper.py", guard())
    link = tmp_path / "main.py"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建文件符号链接")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["helper.py"]


def test_django_manage_entry_gets_dedicated_recipe(tmp_path):
    write(
        tmp_path,
        "manage.py",
        "#!/usr/bin/env python\nimport sys\n"
        "from django.core.management import execute_from_command_line\n"
        "def main():\n    execute_from_command_line(sys.argv)\n"
        "if __name__ == '__main__':\n    main()\n",
    )
    write(tmp_path, "mysite/settings.py", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "python"
    assert d.framework == "django"
    assert d.entry_candidates == ["manage.py"]
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-django"
    recipe = r.recipes[0]
    assert recipe.label == "启动 Django"
    assert recipe.kind == "command"
    assert recipe.args == ["manage.py", "runserver"]


def test_django_manage_plus_settings_without_import_word(tmp_path):
    write(tmp_path, "manage.py", guard())
    write(tmp_path, "config/settings.py", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.framework == "django"
    assert generate_recipes(d, ProjectSettings()).primary_recipe_id == "run-django"


def test_manage_without_django_markers_is_plain_python(tmp_path):
    write(tmp_path, "manage.py", guard())
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "python"
    assert d.framework == ""
    assert d.entry_candidates == ["manage.py"]
    assert generate_recipes(d, ProjectSettings()).primary_recipe_id == "run-python"


def test_requirements_only_with_readme_is_python_without_entry(tmp_path):
    write(tmp_path, "requirements.txt", "requests\n")
    write(tmp_path, "README.md", "run: python -m app")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "python"
    assert d.entry_candidates == []
    assert any("requirements.txt" in item for item in d.evidence)
    r = generate_recipes(d, ProjectSettings())
    assert [recipe.id for recipe in r.recipes] == ["open-directory"]
    assert r.primary_recipe_id == "open-directory"


def test_requirements_alone_is_not_a_project(tmp_path):
    write(tmp_path, "requirements.txt", "requests\n")
    assert detect_project(tmp_path, ProjectSettings()) is None


def package_json(path, data):
    (path / "package.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_node_script_priority_and_all_recipes(tmp_path):
    package_json(
        tmp_path,
        {"scripts": {"start": "node .", "serve": "serve", "preview": "x", "dev": "vite"}},
    )
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "node"
    assert d.scripts == ["dev", "start", "serve", "preview"]
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-dev"
    assert [recipe.id for recipe in r.recipes] == [
        "run-dev",
        "run-start",
        "run-serve",
        "run-preview",
        "open-directory",
    ]
    assert all(recipe.program == "npm" for recipe in r.recipes[:-1])


def test_node_main_field_fallback(tmp_path):
    write(tmp_path, "lib/entry.js", "")
    package_json(tmp_path, {"main": "./lib/entry.js"})
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "node"
    assert d.scripts == []
    assert d.entry_candidates == ["./lib/entry.js"]
    assert any("main 字段" in item for item in d.evidence)
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-node"
    assert r.recipes[0].program == "node"
    assert r.recipes[0].args == ["./lib/entry.js"]


def test_node_main_field_outside_project_is_ignored(tmp_path):
    package_json(tmp_path, {"main": "../outside.js"})
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "node"
    assert d.entry_candidates == []
    assert any("需要配置运行脚本" in item for item in d.evidence)


def test_node_missing_main_falls_back_to_single_entry(tmp_path):
    package_json(tmp_path, {"main": "./missing.js"})
    write(tmp_path, "server.mjs", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["server.mjs"]
    assert any("server.mjs" in item for item in d.evidence)


def test_node_package_without_scripts_and_ambiguous_entries_needs_config(tmp_path):
    package_json(tmp_path, {})
    write(tmp_path, "server.js", "")
    write(tmp_path, "index.js", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "node"
    assert d.entry_candidates == []
    assert any("需要配置运行脚本" in item for item in d.evidence)
    assert generate_recipes(d, ProjectSettings()).primary_recipe_id == "open-directory"


def test_node_framework_inference_generates_exec_recipe(tmp_path):
    package_json(tmp_path, {})
    write(tmp_path, "vite.config.ts", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "node"
    assert d.framework == "vite"
    assert any("框架推断" in item for item in d.evidence)
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-vite"
    assert r.recipes[0].program == "npm"
    assert r.recipes[0].args == ["exec", "--", "vite"]


def test_node_framework_inference_uses_existing_package_manager(tmp_path):
    package_json(tmp_path, {"packageManager": "pnpm@9.0.0"})
    write(tmp_path, "next.config.mjs", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.package_manager == "pnpm"
    assert d.framework == "next"
    r = generate_recipes(d, ProjectSettings())
    assert r.recipes[0].program == "pnpm"
    assert r.recipes[0].args == ["exec", "next", "dev"]


def test_node_scripts_win_over_framework_inference(tmp_path):
    package_json(tmp_path, {"scripts": {"dev": "vite"}})
    write(tmp_path, "vite.config.js", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.scripts == ["dev"]
    assert d.framework == ""


def test_manifestless_single_node_entry(tmp_path):
    write(tmp_path, "server.mjs", "")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "node"
    assert d.entry_candidates == ["server.mjs"]
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-node"
    assert r.recipes[0].program == "node"


def test_manifestless_node_yields_to_static_html(tmp_path):
    write(tmp_path, "index.html", "<h1>x</h1>")
    write(tmp_path, "server.mjs", "")
    assert detect_project(tmp_path, ProjectSettings()).type == "web"


def test_go_root_package_main(tmp_path):
    write(tmp_path, "go.mod", "module example.com/demo\n")
    write(tmp_path, "main.go", "package main\n\nfunc main() {}\n")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "go"
    assert d.entry_candidates == ["."]
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-go"
    assert r.recipes[0].program == "go"
    assert r.recipes[0].args == ["run", "."]


def test_go_cmd_layout(tmp_path):
    write(tmp_path, "go.mod", "module example.com/demo\n")
    write(tmp_path, "cmd/api/main.go", "package main\n\nfunc main() {}\n")
    write(tmp_path, "internal/panel/index.html", "<h1>panel</h1>")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "go"
    assert d.entry_candidates == ["./cmd/api"]
    assert any("cmd/api" in item for item in d.evidence)
    r = generate_recipes(d, ProjectSettings())
    assert r.recipes[0].args == ["run", "./cmd/api"]


def test_go_library_without_main_package_not_recognized(tmp_path):
    write(tmp_path, "go.mod", "module example.com/lib\n")
    write(tmp_path, "lib.go", "package lib\n")
    assert detect_project(tmp_path, ProjectSettings()) is None


def test_report_like_html_is_not_a_static_project(tmp_path):
    write(tmp_path, "coverage-report.html", "<h1>coverage</h1>")
    write(tmp_path, "test-report.html", "<h1>test</h1>")
    assert detect_project(tmp_path, ProjectSettings()) is None

    write(tmp_path, "index.html", "<h1>site</h1>")
    detection = detect_project(tmp_path, ProjectSettings())
    assert detection is not None and detection.type == "web"
    assert detection.entry_candidates == ["index.html"]


def test_rust_binary_project(tmp_path):
    write(tmp_path, "Cargo.toml", "[package]\nname = 'demo'\n")
    write(tmp_path, "src/main.rs", "fn main() {}\n")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "rust"
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "run-rust"
    assert r.recipes[0].program == "cargo"
    assert r.recipes[0].args == ["run"]


def test_cargo_library_is_not_rust_project(tmp_path):
    write(tmp_path, "Cargo.toml", "[package]\nname = 'demo'\n")
    write(tmp_path, "src/lib.rs", "")
    assert detect_project(tmp_path, ProjectSettings()) is None


def test_single_non_index_html_is_web_with_open_recipe(tmp_path):
    write(tmp_path, "personal-workbench_home.html", "<h1>x</h1>")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.type == "web"
    assert d.entry_candidates == ["personal-workbench_home.html"]
    r = generate_recipes(d, ProjectSettings())
    assert r.primary_recipe_id == "open-web"
    recipe = r.recipes[0]
    assert recipe.label == "打开网页"
    assert recipe.kind == "url"
    assert recipe.target == str(tmp_path / "personal-workbench_home.html")
    assert r.recipes[-1].id == "open-directory"


def test_multiple_html_prefers_index(tmp_path):
    for name in ["b.html", "index.html", "a.html"]:
        write(tmp_path, name, "<h1>x</h1>")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["index.html"]
    assert "3" in d.evidence[0]
    r = generate_recipes(d, ProjectSettings())
    recipe = r.recipes[0]
    assert recipe.kind == "url"
    assert recipe.target == str(tmp_path / "index.html")


def test_multiple_html_without_index_chooses_sorted_first(tmp_path):
    for name in ["z.html", "a.html"]:
        write(tmp_path, name, "<h1>x</h1>")
    d = detect_project(tmp_path, ProjectSettings())
    assert d.entry_candidates == ["a.html"]
    assert any("按名称选择" in item for item in d.evidence)
    r = generate_recipes(d, ProjectSettings())
    assert r.recipes[0].kind == "url"
    assert r.recipes[0].target == str(tmp_path / "a.html")


def test_nested_html_only_is_not_a_project(tmp_path):
    write(tmp_path, "site/index.html", "<h1>x</h1>")
    assert detect_project(tmp_path, ProjectSettings()) is None
