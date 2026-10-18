"""Source metadata and content endpoints (契约 §3.1 / §4)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.modules.tasks.api import (
    error_response,
    request_data_root,
    storage_error_response,
)
from app.modules.tasks.domain import to_source_metadata
from app.modules.tasks.services.source_files import SourceFileError, read_image
from app.modules.tasks.storage import load_snapshot


router = APIRouter()


@router.get("/sources/{source_id}")
async def get_source(source_id: str, request: Request) -> JSONResponse:
    """返回契约七键元数据，不暴露 relativePath / originalText。"""
    loaded = load_snapshot(request_data_root(request))
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None

    source = loaded.snapshot.sources.get(source_id)
    if source is None:
        return error_response(404, "source_not_found", "来源不存在。")

    return JSONResponse(
        status_code=200,
        content={
            "source": to_source_metadata(source).model_dump(
                mode="json", by_alias=True
            )
        },
    )


@router.get("/sources/{source_id}/content")
async def get_source_content(source_id: str, request: Request) -> Response:
    """文字源返回原样字节；图片源返回原始字节 + image/png|image/jpeg（T11）。"""
    loaded = load_snapshot(request_data_root(request))
    if loaded.error is not None:
        return storage_error_response(loaded.error)
    assert loaded.snapshot is not None

    source = loaded.snapshot.sources.get(source_id)
    if source is None:
        return error_response(404, "source_not_found", "来源不存在。")

    if source.kind == "image":
        # 按 relativePath 回读原图；文件缺失 → 410 source_content_missing
        try:
            data = read_image(request_data_root(request), str(source.relative_path))
        except SourceFileError as exc:
            return error_response(
                exc.status, exc.code, exc.message, extra_details=exc.details or None
            )
        return Response(content=data, media_type=source.mime_type)

    # 原样返回用户粘贴的原文，不清洗首尾空白或换行
    return Response(
        content=source.original_text or "",
        media_type="text/plain; charset=utf-8",
    )
