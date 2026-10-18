"""仅含「待办清单」模块的独立 FastAPI 应用（测试/自检用）。

与源项目 ``app.main.create_app`` 的差异（按移植任务要求）：
- 不挂 ``/`` 首页与 ``/static`` 前端静态目录（工作台前端由 app/web 提供）；
- 数据根由参数显式注入 ``app.state.data_root``，不做项目内 data/ 硬编码；
- 路由组装复用 ``module.create_router()``，保证与工作台集成路径完全一致。
"""

from pathlib import Path

from fastapi import FastAPI

from .api import DEFAULT_DATA_ROOT
from .module import create_router


def create_tasks_app(root: Path | None = None) -> FastAPI:
    """返回只含本模块的 FastAPI 应用；``root`` 是 state.json/sources 的数据根。"""
    application = FastAPI(
        title="Snap2Todo tasks module",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.data_root = (
        Path(root) if root is not None else DEFAULT_DATA_ROOT
    )

    @application.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(create_router())
    return application
