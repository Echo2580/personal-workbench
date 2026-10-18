"""HTTP API package: shared error envelope, data-root access, router assembly.

Implements 协作/设计/数据与接口契约-v0.1 §4 / §4.2 / §5 for the task and source
endpoints owned by T06.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Mapping

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


logger = logging.getLogger("snap2todo.api")

# Asia/Shanghai 自 1991 年起无夏令时，固定 +08:00 等价；本机无 IANA tzdata 且
# 不新增依赖，故用固定偏移（契约要求的时间戳形式同为 +08:00）。
SHANGHAI = timezone(timedelta(hours=8))


def current_time() -> datetime:
    """统一时钟读取点（T06 引入，T16 项①上移到此公共处）。"""
    return datetime.now(SHANGHAI)

# Workbench 集成时由宿主注入 app.state.data_root（<工作台数据目录>/tasks）；
# 这里仅保留 create_tasks_app() 未传 root 时的兜底值，指向仓库根 data/，
# 正常集成路径不会实际使用它。文件只在首次成功写入时才创建。
DEFAULT_DATA_ROOT: Path = Path(__file__).resolve().parents[4] / "data"

# 契约 §2：持久化字段固定为这三类存储错误码。
_STORAGE_ERROR_CODES = frozenset(
    {
        "storage_read_failed",
        "storage_write_failed",
        "storage_version_unsupported",
    }
)


@dataclass
class FieldError:
    field: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass
class ApiError:
    status_code: int
    code: str
    message: str
    field_errors: list[FieldError] = dataclass_field(default_factory=list)
    extra_details: dict[str, Any] = dataclass_field(default_factory=dict)

    def details(self) -> dict[str, Any]:
        if self.field_errors:
            return {"fieldErrors": [fe.as_dict() for fe in self.field_errors]}
        return dict(self.extra_details)


def error_response(
    status_code: int,
    code: str,
    message: str,
    field_errors: list[FieldError] | None = None,
    extra_details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    """Build the §5 error envelope: {"error": {code, message, details}}."""
    error = ApiError(
        status_code=status_code,
        code=code,
        message=message,
        field_errors=list(field_errors or []),
        extra_details=dict(extra_details or {}),
    )
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details(),
            }
        },
    )


def api_error_response(error: ApiError) -> JSONResponse:
    return error_response(
        error.status_code,
        error.code,
        error.message,
        error.field_errors,
        error.extra_details,
    )


def storage_error_response(error: Mapping[str, Any]) -> JSONResponse:
    """Map an app.modules.tasks.storage error dict onto the §5 storage error envelope."""
    code = str(error.get("code", "storage_read_failed"))
    if code not in _STORAGE_ERROR_CODES:
        code = "storage_read_failed"
    return error_response(500, code, str(error.get("message", "存储操作失败。")))


def request_data_root(request: Request) -> Path:
    return Path(request.app.state.data_root)


def note_commit_warning(operation: str, result: Any) -> None:
    """Record a commit warning (e.g. backup_not_refreshed) without changing
    the HTTP success semantics (T06 任务单关键边界 / QA-P05-R2-r1 O-05)."""
    warning = getattr(result, "warning", None)
    if warning:
        logger.warning(
            "%s committed with warning %s: %s",
            operation,
            warning.get("code"),
            warning.get("message"),
        )


# Router assembly. Imported last so the helpers above exist when the sub
# modules do `from app.modules.tasks.api import ...`.
from app.modules.tasks.api import goals as _goals  # noqa: E402
from app.modules.tasks.api import sources as _sources  # noqa: E402
from app.modules.tasks.api import tasks as _tasks  # noqa: E402

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(_tasks.router)
api_router.include_router(_goals.router)
api_router.include_router(_sources.router)

__all__ = [
    "ApiError",
    "FieldError",
    "DEFAULT_DATA_ROOT",
    "api_router",
    "api_error_response",
    "error_response",
    "note_commit_warning",
    "request_data_root",
    "storage_error_response",
]
