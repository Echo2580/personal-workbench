import json
from pathlib import Path

import pytest

from app.modules.projects.detectors import detect_project
from app.modules.projects.models import ProjectSettings
from app.modules.projects.recipes import generate_recipes
from app.modules.projects.scanner import scan_roots


def put(root, name, text):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_python_application_root_does_not_register_its_selftest_modules(tmp_path):
    put(tmp_path, "README.md", "# Werewolf\n")
    put(tmp_path, "main.py", "if __name__ == '__main__': print('game')\n")
    put(tmp_path, "game/actor.py", "if __name__ == '__main__': print('selftest')\n")
    put(tmp_path, "scripts/check.py", "if __name__ == '__main__': print('check')\n")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert [Path(p.path) for p in result.projects] == [tmp_path]


def test_static_application_assets_and_harnesses_are_not_independent_projects(tmp_path):
    put(tmp_path, "index.html", '<script src="js/app.js"></script>')
    put(tmp_path, "js/app.js", "document.body.textContent = 'app';")
    put(tmp_path, "test/editor-harness.html", "<h1>test</h1>")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert [Path(p.path) for p in result.projects] == [tmp_path]


def test_html_collection_still_discovers_independent_child_application(tmp_path):
    put(tmp_path, "index.html", "<h1>Project collection</h1>")
    put(tmp_path, "site/package.json", '{"scripts":{"dev":"vite"}}')
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert {Path(p.path) for p in result.projects} == {tmp_path, tmp_path / "site"}


def test_html_collection_assets_do_not_hide_nested_independent_applications(tmp_path):
    put(tmp_path, "index.html", '<link rel="stylesheet" href="css/site.css">')
    put(tmp_path, "css/site.css", "body {}")
    put(tmp_path, "apps/site/package.json", '{"scripts":{"dev":"vite"}}')
    put(tmp_path, "test/harness.html", "<h1>Internal harness</h1>")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert {Path(p.path) for p in result.projects} == {
        tmp_path,
        tmp_path / "apps" / "site",
    }


def test_explicit_nested_html_scan_root_remains_reachable(tmp_path):
    put(tmp_path, "index.html", '<link rel="stylesheet" href="css/site.css">')
    put(tmp_path, "css/site.css", "body {}")
    put(tmp_path, "child/index.html", "<h1>Independent site</h1>")
    result = scan_roots(
        ProjectSettings(roots=[str(tmp_path), str(tmp_path / "child")]), []
    )
    assert {Path(p.path) for p in result.projects} == {tmp_path, tmp_path / "child"}


@pytest.mark.parametrize(
    "source",
    [
        "window.addEventListener('load', () => {});",
        "document.body.innerHTML = '';",
        "export const value = 1;",
    ],
)
def test_browser_or_library_entry_is_not_guessed_as_node_program(tmp_path, source):
    put(tmp_path, "app.js", source)
    assert detect_project(tmp_path, ProjectSettings()) is None


def test_node_package_main_export_is_not_assumed_executable(tmp_path):
    put(tmp_path, "package.json", '{"name":"my-library","main":"lib/index.js"}')
    put(tmp_path, "lib/index.js", "module.exports = {answer: 42};")
    detection = detect_project(tmp_path, ProjectSettings())
    assert detection.type == "node"
    assert (
        generate_recipes(detection, ProjectSettings()).primary_recipe_id
        == "open-directory"
    )


def test_multiple_go_commands_require_choice_instead_of_alphabetical_credit_tool(
    tmp_path,
):
    put(tmp_path, "go.mod", "module example.com/app\n")
    for name in ("credit", "server"):
        put(tmp_path, f"cmd/{name}/main.go", "package main\nfunc main() {}\n")
    detection = detect_project(tmp_path, ProjectSettings())
    assert detection.entry_candidates == ["./cmd/credit", "./cmd/server"]
    assert (
        generate_recipes(detection, ProjectSettings()).primary_recipe_id
        == "open-directory"
    )
    assert any("选择" in evidence for evidence in detection.evidence)


@pytest.mark.parametrize(
    "manifest,text,want",
    [
        (
            "README.md",
            "# homeplate · AI 家电保养与维修助手\n",
            "homeplate · AI 家电保养与维修助手",
        ),
        (
            "package.json",
            json.dumps(
                {"name": "named-application", "scripts": {"start": "node server.js"}}
            ),
            "named-application",
        ),
        (
            "pyproject.toml",
            '[project]\nname = "named-python-app"\n',
            "named-python-app",
        ),
    ],
)
def test_discovered_default_name_uses_project_metadata(tmp_path, manifest, text, want):
    put(tmp_path, "main.py", "if __name__ == '__main__': print('app')\n")
    put(tmp_path, manifest, text)
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert result.projects[0].name == want


def test_generic_readme_heading_does_not_replace_directory_name(tmp_path):
    put(tmp_path, "main.py", "if __name__ == '__main__': pass\n")
    put(tmp_path, "README.md", "# README\n## Project setup\n")
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert result.projects[0].name == tmp_path.name


def test_workspace_application_names_stay_independent(tmp_path):
    put(tmp_path, "package.json", '{"name":"workspace","workspaces":["packages/*"]}')
    put(
        tmp_path,
        "packages/web/package.json",
        '{"name":"web-client","scripts":{"dev":"vite"}}',
    )
    result = scan_roots(ProjectSettings(roots=[str(tmp_path)]), [])
    assert {p.name for p in result.projects} == {"workspace", "web-client"}


@pytest.mark.parametrize(
    "readme,want",
    [
        (
            '<h1 align="center">WorkBuddy2API Panel</h1>\n```sh\n# 1. 准备配置与数据目录\n```\n',
            "WorkBuddy2API Panel",
        ),
        (
            "```sh\n# shell comment is not a project title\n```\n# Actual Application\n",
            "Actual Application",
        ),
        (
            "~~~python\n# example only\n~~~\n# Actual Application\n",
            "Actual Application",
        ),
    ],
)
def test_name_reader_ignores_code_fences_and_supports_html_title(
    tmp_path, readme, want
):
    put(tmp_path, "main.py", "if __name__ == '__main__': pass\n")
    put(tmp_path, "README.md", readme)
    assert (
        scan_roots(ProjectSettings(roots=[str(tmp_path)]), []).projects[0].name == want
    )


def test_oversized_metadata_uses_directory_name_without_failing_scan(tmp_path):
    put(tmp_path, "main.py", "if __name__ == '__main__': pass\n")
    put(tmp_path, "README.md", "# Too much\n" + "x" * (1024 * 1024))
    assert (
        scan_roots(ProjectSettings(roots=[str(tmp_path)]), []).projects[0].name
        == tmp_path.name
    )


def test_raw_metadata_is_bounded_before_markup_cleanup(tmp_path, monkeypatch):
    from app.modules.projects import metadata

    put(tmp_path, "main.py", "if __name__ == '__main__': pass\n")
    put(tmp_path, "README.md", "# " + "<" * 160000)
    cleanup = metadata.re.sub

    def bounded_cleanup(pattern, replacement, value, *args, **kwargs):
        assert len(value) <= 1024, "Unbounded untrusted text reached markup cleanup"
        return cleanup(pattern, replacement, value, *args, **kwargs)

    monkeypatch.setattr(metadata.re, "sub", bounded_cleanup)
    assert (
        scan_roots(ProjectSettings(roots=[str(tmp_path)]), []).projects[0].name
        == tmp_path.name
    )
