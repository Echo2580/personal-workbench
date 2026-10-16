from .core.contracts import ModuleDefinition


class ModuleRegistry:
    def __init__(self):
        self._modules = []

    def register(self, definition):
        if any(
            m.id == definition.id
            or (
                definition.status == "available"
                and definition.route
                and m.route == definition.route
            )
            for m in self._modules
        ):
            raise ValueError("重复模块 ID 或路由")
        self._modules.append(definition)

    def list_modules(self):
        return list(self._modules)


def default_registry(project_definition=None):
    registry = ModuleRegistry()
    registry.register(
        project_definition
        or ModuleDefinition(
            "projects",
            "项目启动器",
            "发现、配置和运行散落的项目。",
            "projects",
            "/projects",
            "available",
            settings_route="/settings",
        )
    )
    registry.register(
        ModuleDefinition(
            "navigation",
            "快捷导航",
            "把常用网站与工具放在手边。",
            "link",
            None,
            "planned",
        )
    )
    registry.register(
        ModuleDefinition(
            "tasks",
            "待办与日历",
            "集中安排待办事项与日程提醒。",
            "calendar",
            None,
            "planned",
        )
    )
    return registry
