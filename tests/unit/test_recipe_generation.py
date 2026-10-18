import pytest

from app.modules.projects.models import (
    Detection,
    ProjectSettings,
    Recipe,
    RecipeSet,
)
from app.modules.projects.recipes import (
    generate_recipes,
    project_python,
    recipe_fingerprint,
)


def test_invalid_recipe_combinations_and_urls():
    for data in [
        dict(
            id="x",
            label="x",
            kind="command",
            cwd=".",
            program="python",
            shell_command="echo hi",
        ),
        dict(id="x", label="x", kind="url", target="javascript:alert(1)"),
        dict(id="x", label="x", kind="directory", target=".", program="x"),
    ]:
        with pytest.raises(ValueError):
            Recipe(**data)
    with pytest.raises(ValueError):
        RecipeSet(recipes=[], primary_recipe_id="x")


def make_venv_python(root, name):
    target = root / name / "Scripts" / "python.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    return target


def test_project_python_prefers_dot_venv(tmp_path):
    dot_venv = make_venv_python(tmp_path, ".venv")
    make_venv_python(tmp_path, "venv")
    settings = ProjectSettings(default_python="C:/missing/python.exe")
    assert project_python(tmp_path, settings) == str(dot_venv)


def test_project_python_falls_back_to_venv(tmp_path):
    venv = make_venv_python(tmp_path, "venv")
    settings = ProjectSettings(default_python="C:/missing/python.exe")
    assert project_python(tmp_path, settings) == str(venv)


def test_project_python_uses_default_without_project_environment(tmp_path):
    settings = ProjectSettings(default_python="C:/missing/python.exe")
    assert project_python(tmp_path, settings) == "C:/missing/python.exe"


def test_all_auto_recipe_shapes_pass_model_validation(tmp_path):
    settings = ProjectSettings(default_python="C:/missing/python.exe")
    cases = [
        Detection(path=str(tmp_path), type="python", entry_candidates=["todo.py"]),
        Detection(
            path=str(tmp_path),
            type="python",
            entry_candidates=["manage.py"],
            framework="django",
        ),
        Detection(path=str(tmp_path), type="node", scripts=["dev", "start"]),
        Detection(
            path=str(tmp_path),
            type="node",
            framework="vite",
            package_manager="pnpm",
        ),
        Detection(path=str(tmp_path), type="node", entry_candidates=["server.mjs"]),
        Detection(path=str(tmp_path), type="go", entry_candidates=["./cmd/api"]),
        Detection(path=str(tmp_path), type="rust"),
        Detection(path=str(tmp_path), type="web", entry_candidates=["index.html"]),
        Detection(path=str(tmp_path), type="web", entry_candidates=["landing.html"]),
    ]
    for detection in cases:
        generated = generate_recipes(detection, settings)
        RecipeSet.model_validate(generated.model_dump())
        assert generated.recipes[-1].id == "open-directory"
        assert generated.recipes[-1].target == str(tmp_path)
        assert generated.primary_recipe_id == generated.recipes[0].id
        ids = [recipe.id for recipe in generated.recipes]
        assert len(ids) == len(set(ids)), ids


def test_django_recipe_has_dedicated_primary_command(tmp_path):
    detection = Detection(
        path=str(tmp_path),
        type="python",
        entry_candidates=["manage.py"],
        framework="django",
    )
    generated = generate_recipes(
        detection, ProjectSettings(default_python="C:/missing/python.exe")
    )
    primary = generated.recipes[0]
    assert generated.primary_recipe_id == "run-django"
    assert primary.label == "启动 Django"
    assert primary.program == "C:/missing/python.exe"
    assert primary.args == ["manage.py", "runserver"]


def test_node_framework_recipe_keeps_package_manager(tmp_path):
    settings = ProjectSettings()
    expected = {
        "npm": ["exec", "--", "next", "dev"],
        "pnpm": ["exec", "next", "dev"],
        "yarn": ["exec", "next", "dev"],
        "bun": ["x", "next", "dev"],
    }
    for manager, args in expected.items():
        detection = Detection(
            path=str(tmp_path),
            type="node",
            framework="next",
            package_manager=manager,
        )
        recipe = generate_recipes(detection, settings).recipes[0]
        assert recipe.program == manager
        assert recipe.args == args


def test_go_and_rust_recipes_use_plain_windows_programs(tmp_path):
    settings = ProjectSettings()
    go = generate_recipes(
        Detection(path=str(tmp_path), type="go", entry_candidates=[]), settings
    ).recipes[0]
    assert (go.program, go.args) == ("go", ["run", "."])
    rust = generate_recipes(Detection(path=str(tmp_path), type="rust"), settings).recipes[0]
    assert (rust.program, rust.args) == ("cargo", ["run"])


def test_web_non_index_uses_static_url_recipe(tmp_path):
    page = tmp_path / "start.html"
    page.write_text("<h1>x</h1>", encoding="utf-8")
    generated = generate_recipes(
        Detection(path=str(tmp_path), type="web", entry_candidates=["start.html"]),
        ProjectSettings(),
    )
    recipe = generated.recipes[0]
    assert generated.primary_recipe_id == "open-web"
    assert recipe.kind == "url"
    assert recipe.target == str(page)


def test_static_url_recipe_is_limited_to_project_html(tmp_path):
    from app.core.contracts import WorkbenchError
    from app.modules.projects.service import ProjectService

    project = tmp_path / "proj"
    (project / "sub").mkdir(parents=True)
    page = project / "sub" / "landing.html"
    page.write_text("<h1>x</h1>", encoding="utf-8")
    outside = tmp_path / "outside.html"
    outside.write_text("<h1>x</h1>", encoding="utf-8")

    class DummyProject:
        path = str(project)

    ok = Recipe(id="open-web", label="打开网页", kind="url", target=str(page))
    ProjectService.check_recipe_paths(
        None, DummyProject(), RecipeSet(recipes=[ok], primary_recipe_id="open-web")
    )

    bad = Recipe(id="open-web", label="打开网页", kind="url", target=str(outside))
    with pytest.raises(WorkbenchError):
        ProjectService.check_recipe_paths(
            None, DummyProject(), RecipeSet(recipes=[bad], primary_recipe_id="open-web")
        )


def test_open_action_opens_project_html_in_browser(tmp_path, monkeypatch):
    from app.modules.projects import actions

    page = tmp_path / "landing.html"
    page.write_text("<h1>x</h1>", encoding="utf-8")
    opened = []
    monkeypatch.setattr(actions.webbrowser, "open", lambda target: opened.append(target) or True)
    recipe = Recipe(id="open-web", label="打开网页", kind="url", target=str(page))
    result = actions.OpenActionService().execute(recipe)
    assert result["status"] == "open_requested"
    assert opened == [page.as_uri()]


def test_new_recipe_fingerprints_are_stable(tmp_path):
    settings = ProjectSettings()
    detection = Detection(
        path=str(tmp_path), type="go", entry_candidates=["./cmd/api"]
    )
    first = [recipe_fingerprint("pid", recipe) for recipe in generate_recipes(detection, settings).recipes]
    second = [recipe_fingerprint("pid", recipe) for recipe in generate_recipes(detection, settings).recipes]
    assert first == second
