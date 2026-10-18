from pathlib import Path
from contextlib import asynccontextmanager
from .modules.projects.service import ProjectService
from .modules.projects.runtime import RuntimeManager
from .modules.projects.module import definition
from uuid import uuid4
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from . import __version__
from .core.config_files import resolve_data_dir
from .core.contracts import WorkbenchError
from .core.shutdown import ShutdownCoordinator
from pydantic import BaseModel, ConfigDict
import os
from .core.security import create_session_token, install_security, error_response
from .module_registry import default_registry
from .modules.backup.module import definition as backup_definition
from .modules.home.module import definition as home_definition


def create_app(data_dir=None, extra_modules=()):
    service = ProjectService(resolve_data_dir(data_dir), str(uuid4()))

    @asynccontextmanager
    async def lifespan(app):
        service.runtime = RuntimeManager(service.data_dir, service.instance_id)
        service.start()
        try:
            yield
        finally:
            service.close()
            if service.runtime:
                service.runtime.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.data_dir = resolve_data_dir(data_dir)
    # 待办模块（Snap2Todo 原生模块）的数据根：<工作台数据目录>/tasks。
    # 目录不预创建，模块首次成功写入时才落盘。
    app.state.data_root = app.state.data_dir / "tasks"
    app.state.token = create_session_token()
    app.state.instance_id = service.instance_id
    app.state.projects = service
    app.state.shutdown_callback = lambda: None
    shutdown = ShutdownCoordinator(
        lock=service.lock,
        running_items=service.shutdown_items,
        stop_all=lambda: service.runtime.stop_all(),
        block_actions=service.block_actions,
        on_shutdown=lambda: app.state.shutdown_callback(),
    )
    app.state.registry = default_registry(definition(service))
    # 首页数据服务（天气/段子/随手记）：只有 API，没有导航路由。
    app.state.registry.register(home_definition())
    # 数据备份服务（导出/恢复/概览）：只有 API，没有导航路由。
    app.state.registry.register(backup_definition())
    for module in extra_modules:
        app.state.registry.register(module)
    for module in app.state.registry.list_modules():
        if module.router:
            app.include_router(module.router)
    install_security(app)

    @app.exception_handler(WorkbenchError)
    async def domain_error(request, e):
        return error_response(e.code, e.message, e.status, e.details, e.recovery_action)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, e):
        return error_response("validation_error", "输入无效，请检查字段。", 422, str(e))

    @app.get("/healthz")
    def health():
        return {"service": "personal-workbench", "version": __version__, "ready": True}

    @app.get("/api/v1/bootstrap")
    def bootstrap():
        return {
            "token": app.state.token,
            "instance_id": app.state.instance_id,
            "version": __version__,
            "modules": [m.public() for m in app.state.registry.list_modules()],
        }

    @app.get("/api/v1/instance")
    def instance():
        return {"instance_id": app.state.instance_id, "version": __version__}

    class ShutdownInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        confirmed_stop_running: bool

    @app.get("/api/v1/system/about")
    def about():
        return {"version": __version__, "data_dir": str(app.state.data_dir)}

    @app.post("/api/v1/system/open-data-directory")
    def open_data():
        os.startfile(str(app.state.data_dir))
        return {"status": "open_requested"}

    @app.get("/api/v1/system/shutdown-preview")
    def shutdown_preview():
        return shutdown.preview()

    @app.post("/api/v1/system/shutdown")
    def exit_workbench(body: ShutdownInput):
        return shutdown.request(body.confirmed_stop_running)

    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web"
    )
    return app
