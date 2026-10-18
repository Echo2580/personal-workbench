import hashlib
import json
import shutil
import sys
from pathlib import Path
from .detectors import NODE_FRAMEWORKS, node_framework_args
from .models import Recipe, RecipeSet


def project_python(path, settings):
    for name in (".venv", "venv"):
        local = Path(path) / name / "Scripts" / "python.exe"
        if local.is_file():
            return str(local)
    if settings.default_python:
        return settings.default_python
    found = shutil.which("python.exe")
    if found and Path(found).parent.parent.resolve() != Path(sys.prefix).resolve():
        return found
    # pythonw service must not make its own venv the implicit project environment.
    base = Path(sys.base_prefix) / "python.exe"
    return str(base) if base.is_file() else "python.exe"


def _node_framework_recipe(detection, path):
    for name, _config, _suffixes, command, label in NODE_FRAMEWORKS:
        if name != detection.framework:
            continue
        return Recipe(
            id="run-" + name,
            label="运行 " + label,
            kind="command",
            cwd=str(path),
            program=detection.package_manager,
            args=node_framework_args(detection.package_manager, command),
        )
    return None


def _web_recipe(detection, path):
    name = (
        detection.entry_candidates[0]
        if len(detection.entry_candidates) == 1
        else "index.html"
    )
    target = path / name
    return Recipe(id="open-web", label="打开网页", kind="url", target=str(target))


def generate_recipes(detection, settings):
    path = Path(detection.path)
    recipes = []
    if detection.type == "python":
        if detection.framework == "django" and detection.entry_candidates == [
            "manage.py"
        ]:
            recipes.append(
                Recipe(
                    id="run-django",
                    label="启动 Django",
                    kind="command",
                    cwd=str(path),
                    program=project_python(path, settings),
                    args=["manage.py", "runserver"],
                )
            )
        elif len(detection.entry_candidates) == 1:
            recipes.append(
                Recipe(
                    id="run-python",
                    label="运行 Python",
                    kind="command",
                    cwd=str(path),
                    program=project_python(path, settings),
                    args=[detection.entry_candidates[0]],
                )
            )
    elif detection.type == "node":
        for script in detection.scripts:
            recipes.append(
                Recipe(
                    id="run-" + script,
                    label="运行 " + script,
                    kind="command",
                    cwd=str(path),
                    program=detection.package_manager,
                    args=["run", script],
                )
            )
        if not recipes:
            framework = _node_framework_recipe(detection, path)
            if framework:
                recipes.append(framework)
            elif len(detection.entry_candidates) == 1:
                entry = detection.entry_candidates[0]
                recipes.append(
                    Recipe(
                        id="run-node",
                        label="运行 Node",
                        kind="command",
                        cwd=str(path),
                        program="node",
                        args=[entry],
                    )
                )
    elif detection.type == "go":
        recipes.append(
            Recipe(
                id="run-go",
                label="运行 Go",
                kind="command",
                cwd=str(path),
                program="go",
                args=["run", *(detection.entry_candidates or ["."])],
            )
        )
    elif detection.type == "rust":
        recipes.append(
            Recipe(
                id="run-rust",
                label="运行 Rust",
                kind="command",
                cwd=str(path),
                program="cargo",
                args=["run"],
            )
        )
    elif detection.type == "web":
        recipes.append(_web_recipe(detection, path))
    recipes.append(
        Recipe(
            id="open-directory", label="打开文件夹", kind="directory", target=str(path)
        )
    )
    return RecipeSet(recipes=recipes, primary_recipe_id=recipes[0].id)


def recipe_fingerprint(project_id, recipe):
    content = {"project_id": project_id, **recipe.model_dump()}
    return hashlib.sha256(
        json.dumps(
            content, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
