"""数据备份接口：导出 / 恢复 / 概览。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app import __version__
from app.core.security import error_response
from app.modules.backup import service

router = APIRouter(prefix="/api/v1/backup")


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir)


def _projects(request: Request):
    return getattr(request.app.state, "projects", None)


def _failure(exc: service.BackupError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.status)


@router.get("/export")
def export_backup(request: Request) -> Response:
    bundle = service.collect_bundle(_data_dir(request), __version__)
    payload = json.dumps(bundle, ensure_ascii=False, indent=2)
    filename = service.export_filename()
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/info")
def backup_info(request: Request) -> JSONResponse:
    info = service.collect_info(_data_dir(request), _projects(request), __version__)
    return JSONResponse(status_code=200, content=info)


@router.post("/restore")
async def restore_backup(request: Request) -> JSONResponse:
    raw = await request.body()
    if len(raw) > service.MAX_RESTORE_BYTES:
        return error_response("backup_too_large", "备份文件过大（上限 20 MB）。", 413)
    if not raw.strip():
        return error_response("invalid_backup", "备份内容为空。", 400)
    try:
        bundle = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return error_response("invalid_backup", "备份文件不是合法的 UTF-8 JSON。", 400)
    try:
        outcome = service.restore_bundle(_data_dir(request), bundle, _projects(request), __version__)
    except service.BackupError as exc:
        return _failure(exc)
    return JSONResponse(status_code=200, content=outcome)
