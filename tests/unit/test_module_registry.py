import pytest
from app.module_registry import default_registry
from app.core.contracts import ModuleDefinition


def test_extension_and_duplicate_routes():
    r = default_registry()
    r.register(
        ModuleDefinition(
            id="notes",
            title="笔记",
            description="test",
            icon="note",
            route="/notes",
            status="available",
        )
    )
    assert [m.id for m in r.list_modules()] == [
        "projects",
        "tasks",
        "notes",
    ]
    with pytest.raises(ValueError):
        r.register(
            ModuleDefinition(
                id="notes2",
                title="重复",
                description="",
                icon="note",
                route="/notes",
                status="available",
            )
        )
