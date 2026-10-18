"""工作台「待办清单」模块定义。

Snap2Todo 原有三组路由（tasks/sources、extractions、reminder-sessions）各自
自带路径前缀，这里组合成一个**无前缀** APIRouter 交给 ModuleDefinition：

- ``api_router``（tasks + sources）本身已带 ``/api/v1`` 前缀；
- ``extractions_router``、``reminder_sessions_router`` 在源应用中由
  ``create_app`` 用 ``prefix="/api/v1"`` 挂载，这里同样补齐。

最终工作台 ``app.include_router(module.router)`` 后路径与源项目保持一致：
``/api/v1/tasks``、``/api/v1/sources/...``、``/api/v1/extractions``、
``/api/v1/draft-sets/...``、``/api/v1/reminder-sessions``、``/api/v1/reminders/...``。
"""

from fastapi import APIRouter

from ...core.contracts import ModuleDefinition
from .api import api_router
from .api.extractions import router as extractions_router
from .api.reminder_sessions import router as reminder_sessions_router


def create_router() -> APIRouter:
    """组合出无前缀 router；每次调用返回新的 router 实例，避免多应用共享状态。"""
    router = APIRouter()
    router.include_router(api_router)
    router.include_router(extractions_router, prefix="/api/v1")
    router.include_router(reminder_sessions_router, prefix="/api/v1")
    return router


def definition() -> ModuleDefinition:
    """工作台模块注册入口（构造参数按 app/core/contracts.py 的字段顺序）。"""
    return ModuleDefinition(
        "tasks",
        "待办清单",
        "把通知截图整理成待办。",
        "checklist",
        "/tasks",
        "available",
        router=create_router(),
    )
