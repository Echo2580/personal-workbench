"""测试专用 FastAPI 包装：给 create_tasks_app 补回源项目的 ``/`` 与 ``/static``。

背景
----
源项目 ``app.main.create_app`` 除了 ``/health`` + ``/api/v1/*`` 外，还挂载了：

- ``GET /``         → 返回 ``web/index.html``；
- ``/static``       → ``StaticFiles(directory=web/)``。

移植后的 ``app.modules.tasks.app_factory.create_tasks_app`` 按工作台约定**只保留**
``/health`` 与 ``/api/v1/*``（工作台前端另由 app/web 提供）。但原 Snap2Todo 测试套件
里有一批用例断言首页可访问、静态资源可访问（test_bootstrap、test_frontend_*、
test_api_*），因此在本测试目录内做**等价包装**：不改产品代码，只在测试侧复现源应用
的 ``/`` 与 ``/static`` 行为。静态资源来自随测试一起复制的 ``tests/tasks/web/``
（源 ``web/`` 的只读副本）。

用法：测试中原 ``from app.main import create_app`` 改写为
``from tasks_test_app import create_app``，签名与语义保持一致。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.modules.tasks.app_factory import create_tasks_app

WEB_DIR = Path(__file__).resolve().parent / "web"
HOME_PAGE = WEB_DIR / "index.html"


def create_app(root: Path | None = None) -> FastAPI:
    """``create_tasks_app(root)`` + 源项目同款首页与静态目录挂载。"""
    application = create_tasks_app(root)

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home() -> HTMLResponse:
        return HTMLResponse(HOME_PAGE.read_text(encoding="utf-8"))

    application.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR)),
        name="static",
    )
    return application
