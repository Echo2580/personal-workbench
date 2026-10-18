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


def _tasks_definition():
    """待办模块（Snap2Todo 原生模块）。

    仅在依赖缺失（未按 requirements.lock 安装 httpx / python-multipart）时降级为
    「规划中」占位，避免旧安装升级后整个工作台起不来；其余导入异常仍应抛出，
    否则真实缺陷会被静默吞掉。
    """
    try:
        from .modules.tasks.module import definition

        return definition()
    except ImportError:  # pragma: no cover - 依赖缺失时的降级路径
        return ModuleDefinition(
            "tasks",
            "待办清单",
            "把通知截图整理成待办。",
            "checklist",
            None,
            "planned",
        )


def default_registry(project_definition=None, tasks_definition=None):
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
    registry.register(tasks_definition or _tasks_definition())
    return registry
