import hashlib
import json
import shutil
import sys
from pathlib import Path
from .models import Recipe, RecipeSet


def project_python(path, settings):
    local = Path(path) / ".venv" / "Scripts" / "python.exe"
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


def generate_recipes(detection, settings):
    path = Path(detection.path)
    recipes = []
    if detection.type == "python" and len(detection.entry_candidates) == 1:
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
    elif detection.type == "web":
        recipes.append(
            Recipe(
                id="open-web",
                label="打开网页",
                kind="url",
                target=str(path / "index.html"),
            )
        )
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
