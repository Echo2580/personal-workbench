from ...core.contracts import ModuleDefinition
from .router import create_router


def definition(service):
    return ModuleDefinition(
        "projects",
        "项目启动器",
        "发现、配置和运行散落的项目。",
        "projects",
        "/projects",
        "available",
        router=create_router(service),
        summary_provider=service.summary,
        settings_route="/settings",
    )
