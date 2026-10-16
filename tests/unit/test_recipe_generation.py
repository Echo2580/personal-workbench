import pytest
from app.modules.projects.models import Recipe, RecipeSet


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
