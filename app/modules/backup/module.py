"""数据备份模块定义（API-only，无导航路由）。"""

from __future__ import annotations

from app.core.contracts import ModuleDefinition

from app.modules.backup.router import router


def definition() -> ModuleDefinition:
    return ModuleDefinition(
        "backup",
        "数据备份",
        "导出与恢复工作台数据。",
        "archive",
        None,
        "available",
        router=router,
    )
