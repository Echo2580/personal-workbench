"""首页数据服务模块定义（无路由，仅提供 API）。"""

from __future__ import annotations

from app.core.contracts import ModuleDefinition

from app.modules.home.router import router


def definition() -> ModuleDefinition:
    """route=None + status=available：外壳导航会跳过「可用但无路由」的模块。"""
    return ModuleDefinition(
        "home",
        "首页数据",
        "天气、每日段子与随手记服务。",
        "widget",
        None,
        "available",
        router=router,
    )
