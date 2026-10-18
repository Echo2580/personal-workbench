"""Extraction and confirmation endpoints (契约 §4 / §4.1)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.modules.tasks.api import (
    FieldError,
    api_error_response,
    current_time,
    error_response,
    request_data_root,
)
from app.modules.tasks.api.dto import validation_error_to_api_error
from app.modules.tasks.services.source_files import (
    SourceFileError,
    sanitize_file_name,
    store_image,
    validate_image_bytes,
)
from app.modules.tasks.services.confirmation import confirm_draft_set
from app.modules.tasks.services.extraction import (
    DraftSetCache,
    DraftSetCacheEntry,
    DraftValidationError,
    run_extraction,
    run_image_extraction,
)
from app.modules.tasks.services.model_adapter import (
    DeepSeekExtractionModel,
    ExtractionModel,
    ImageExtractionModel,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)


router = APIRouter()
logger = logging.getLogger("snap2todo.api")

# 项⑤：对外固定文案（细节不进响应）
MODEL_ERROR_TEXT_FIXED = {"model_unavailable": "模型服务暂不可用，请稍后重试。"}

# Asia/Shanghai 固定 +08:00（本机无 IANA tzdata；与 T06 同一取舍）
SHANGHAI = timezone(timedelta(hours=8))

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_EXTRACTION_ROOT_KEYS = ("source",)
_EXTRACTION_SOURCE_KEYS = ("kind", "originalText", "messageDate")


def current_time() -> datetime:
    return datetime.now(SHANGHAI)


def get_model(request: Request) -> ExtractionModel:
    """Return the injected adapter, defaulting to the DeepSeek implementation."""
    model = getattr(request.app.state, "extraction_model", None)
    if model is None:
        model = DeepSeekExtractionModel()
        request.app.state.extraction_model = model
    return model


def get_cache(request: Request) -> DraftSetCache:
    """Per-app-instance draft cache; a restart naturally yields an empty one."""
    cache = getattr(request.app.state, "draft_set_cache", None)
    if cache is None:
        cache = DraftSetCache()
        request.app.state.draft_set_cache = cache
    return cache


def get_image_model(request: Request) -> ImageExtractionModel:
    """图片提取适配器：注入的适配器不支持图片入口时按不可用处理（503）。"""
    model = get_model(request)
    if not hasattr(model, "extract_drafts_from_image"):
        raise ModelUnavailableError("注入的模型适配器不支持图片提取。")
    return model  # type: ignore[return-value]


def _extraction_failure(exc: Exception) -> JSONResponse:
    """§5 失败分型：503/504/502×2。异常细节只进日志，不进响应。"""
    if isinstance(exc, ModelUnavailableError):
        # 项⑤：对外固定文案，异常细节（含后端原始描述）只进日志；
        # 日志与响应均不得包含密钥（凭据仅存在于适配器内存）。
        logger.warning("模型服务不可用（已脱敏）：%s", type(exc).__name__)
        return error_response(
            503, "model_unavailable", MODEL_ERROR_TEXT_FIXED["model_unavailable"]
        )
    if isinstance(exc, ModelTimeoutError):
        return error_response(504, "extraction_timeout", "模型调用超时，请重试。")
    if isinstance(exc, ModelOutputInvalidError):
        return error_response(502, "model_output_invalid", "模型输出无法解析。")
    validation = exc if isinstance(exc, DraftValidationError) else None
    field_errors: list[FieldError] = []
    if validation is not None and validation.validation_error is not None:
        mapped = validation_error_to_api_error(
            validation.validation_error, prefix=f"drafts[{validation.index}]"
        )
        field_errors = mapped.field_errors
    return error_response(
        502,
        "draft_validation_failed",
        "模型输出的草稿字段不合法。",
        field_errors=field_errors,
    )


async def _read_json_object(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - any parse failure is a 400
        return error_response(400, "invalid_request", "请求体必须是合法 JSON。")
    if not isinstance(payload, dict):
        return error_response(400, "invalid_request", "请求体必须是 JSON 对象。")
    return payload


def _unknown_keys(payload: dict[str, Any], allowed: tuple[str, ...]) -> list[str]:
    return [key for key in payload if key not in allowed]


def _field_error(field: str, code: str, message: str) -> FieldError:
    return FieldError(field, code, message)


def _is_multipart(request: Request) -> bool:
    content_type = request.headers.get("content-type", "")
    return content_type.lower().startswith("multipart/form-data")


def _parse_message_date_part(raw: str | None) -> tuple[str | None, JSONResponse | None]:
    """multipart messageDate 部件：省略 → null；空串或字面 "null" → 400（契约 §4.2）。"""
    if raw is None:
        return None, None
    if raw.strip() == "" or raw.strip().lower() == "null":
        return None, error_response(
            400,
            "invalid_request",
            "messageDate 部件为空或字面 null 时返回 400；请省略该部件或给出合法日期。",
            field_errors=[
                _field_error("messageDate", "invalid_date", "必须是合法 YYYY-MM-DD。")
            ],
        )
    if not _DATE_PATTERN.fullmatch(raw.strip()):
        return None, error_response(
            400,
            "invalid_request",
            "messageDate 必须是 YYYY-MM-DD。",
            field_errors=[
                _field_error("messageDate", "invalid_date", "必须是合法 YYYY-MM-DD。")
            ],
        )
    try:
        datetime.fromisoformat(raw.strip())
    except ValueError:
        return None, error_response(
            400,
            "invalid_request",
            "messageDate 不是真实日历日期。",
            field_errors=[
                _field_error("messageDate", "invalid_date", "必须是真实日历日期。")
            ],
        )
    return raw.strip(), None


async def _read_multipart_image(request: Request):
    """读取 multipart 的 file 与 messageDate 部件，返回 (UploadFile, messageDate) 或错误响应。"""
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 - multipart 解析失败
        return None, error_response(400, "invalid_request", "multipart 请求解析失败。")

    upload = form.get("file")
    if upload is None:
        return None, error_response(
            400,
            "invalid_request",
            "multipart 必须包含 file 部件。",
            field_errors=[_field_error("file", "missing", "缺少 file 部件。")],
        )

    raw_date = None
    if "messageDate" in form:
        value = form.get("messageDate")
        raw_date = value if isinstance(value, str) else str(value)

    message_date, failure = _parse_message_date_part(raw_date)
    if failure is not None:
        return None, failure
    return (upload, message_date), None


async def _handle_image_extraction(request: Request) -> JSONResponse:
    """图片提取（T12）：校验 → 落盘（T11 不变）→ 锁外调视觉模型 → 200 DraftSet。

    锁内不等模型（§2.1）：字节写入/模型调用全程在存储锁外，提取阶段不写 state.json。
    无任务时图片文件已落盘但未入快照 → 成为 orphan（契约允许，不自动删除）。
    """
    parsed, failure = await _read_multipart_image(request)
    if failure is not None:
        return failure
    upload, message_date = parsed

    data = await upload.read()
    try:
        image = validate_image_bytes(data)
    except SourceFileError as exc:
        return error_response(
            exc.status, exc.code, exc.message, extra_details=exc.details or None
        )

    # 锁外：字节写入 + 重读校验 + 原子移动（T11 协议不变）
    stored = store_image(
        request_data_root(request),
        image,
    )
    logger.info("图片已落盘：%s", stored.relative_path)

    try:
        draft_set, entry = run_image_extraction(
            get_image_model(request),
            image_bytes=image.data,
            content_type=image.content_type,
            message_date=message_date,
            now=current_time(),
            source_id=stored.source_id,
            relative_path=stored.relative_path,
            content_sha256=image.content_sha256,
            file_name=sanitize_file_name(getattr(upload, "filename", None)),
        )
    except (
        ModelUnavailableError,
        ModelTimeoutError,
        ModelOutputInvalidError,
        DraftValidationError,
    ) as exc:
        # 失败不落 JSON、不登记缓存条目、不伪装 no_tasks（图片文件留在磁盘成 orphan）
        return _extraction_failure(exc)

    get_cache(request).put(entry)
    # 提取不写 state.json
    return JSONResponse(
        status_code=200, content=draft_set.model_dump(mode="json", by_alias=True)
    )


async def _read_multipart_confirmation(request: Request):
    """读取图片确认的 multipart：file（原图）+ confirmation（JSON 字符串）部件。"""
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return None, None, error_response(400, "invalid_request", "multipart 请求解析失败。")

    upload = form.get("file")
    if upload is None:
        return None, None, error_response(
            400,
            "invalid_request",
            "multipart 必须包含 file 部件。",
            field_errors=[_field_error("file", "missing", "缺少 file 部件。")],
        )
    raw_confirmation = form.get("confirmation")
    if raw_confirmation is None:
        return None, None, error_response(
            400,
            "invalid_request",
            "图片确认必须包含 confirmation 部件。",
            field_errors=[_field_error("confirmation", "missing", "缺少 confirmation 部件。")],
        )

    try:
        payload = json.loads(raw_confirmation)
    except Exception:  # noqa: BLE001
        return None, None, error_response(
            400,
            "invalid_request",
            "confirmation 部件必须是合法 JSON。",
            field_errors=[_field_error("confirmation", "invalid_json", "必须是合法 JSON。")],
        )
    if not isinstance(payload, dict):
        return None, None, error_response(
            400, "invalid_request", "confirmation 部件必须是 JSON 对象。"
        )

    data = await upload.read()
    try:
        image = validate_image_bytes(data)
    except SourceFileError as exc:
        return None, None, error_response(
            exc.status, exc.code, exc.message, extra_details=exc.details or None
        )
    return payload, image.data, None


def _unknown_field_response(fields: list[str]) -> JSONResponse:
    return error_response(
        400,
        "invalid_request",
        "包含不可写或未知字段。",
        field_errors=[
            _field_error(field, "unknown_field", "该字段不可写或不存在。")
            for field in fields
        ],
    )


def _skeleton_batch_view(
    cache: DraftSetCache, draft_set_id: str, payload: dict[str, Any]
) -> DraftSetCache | None:
    """T11 骨架期：缓存条目没有草稿，批次成员由客户端 confirmedTasks 决定。

    契约 §4.2 的确认请求本身就是「完整输入」（source + confirmedTasks），而 T11
    骨架阶段提取不调用模型、不可能产出草稿，故条目 drafts 为空时用本次提交的
    draftId 构造**请求级**批次视图，让 confirmation 的归属/重复校验在本批次内照常
    生效；共享缓存条目本身不被改写。T12 起条目携带真实草稿，本分支自然失效（drafts
    非空即返回 None，走原有成员的校验）。
    """
    entry = cache.get(draft_set_id)
    if entry is None or entry.drafts:
        return None
    task_items = payload.get("confirmedTasks")
    if not isinstance(task_items, list):
        return None
    draft_ids = [
        item["draftId"]
        for item in task_items
        if isinstance(item, dict) and isinstance(item.get("draftId"), str)
    ]
    if not draft_ids:
        return None  # 空批次交给 confirm_draft_set 返回 422 empty_confirmation
    view = DraftSetCache()
    view.put(
        DraftSetCacheEntry(
            draft_set_id=entry.draft_set_id,
            source=entry.source,
            drafts=[{"id": draft_id} for draft_id in draft_ids],
            created_at=entry.created_at,
        )
    )
    return view


@router.post("/extractions")
async def create_extraction(request: Request) -> JSONResponse:
    # T11：multipart（图片）分支——校验 + 落盘就绪后返回 501 待 T12 接模型
    if _is_multipart(request):
        return await _handle_image_extraction(request)

    payload = await _read_json_object(request)
    if isinstance(payload, JSONResponse):
        return payload

    unknown_root = _unknown_keys(payload, _EXTRACTION_ROOT_KEYS)
    if unknown_root:
        return _unknown_field_response(unknown_root)

    source = payload.get("source")
    if not isinstance(source, dict):
        return error_response(400, "invalid_request", "source 必须是 JSON 对象。")

    unknown_source = _unknown_keys(source, _EXTRACTION_SOURCE_KEYS)
    if unknown_source:
        return _unknown_field_response([f"source.{key}" for key in unknown_source])

    kind = source.get("kind")
    if kind != "text":
        # 图片 multipart 路径属 T11/T12
        return error_response(
            415,
            "unsupported_media_type",
            "当前只支持文字导入（kind=text）；图片路径尚未实现。",
            extra_details={"plannedTask": "T11"},
        )

    original_text = source.get("originalText")
    if not isinstance(original_text, str) or not original_text.strip():
        return error_response(
            400,
            "invalid_request",
            "originalText 必须是非空字符串。",
            field_errors=[
                _field_error("source.originalText", "invalid", "必须是非空字符串。")
            ],
        )

    message_date = source.get("messageDate", None)
    if message_date is not None:
        valid = isinstance(message_date, str) and bool(
            _DATE_PATTERN.fullmatch(message_date)
        )
        if valid:
            try:
                datetime.fromisoformat(message_date)
            except ValueError:
                valid = False
        if not valid:
            return error_response(
                400,
                "invalid_request",
                "messageDate 必须是 YYYY-MM-DD 或 null。",
                field_errors=[
                    _field_error(
                        "source.messageDate", "invalid_date", "必须是真实日历日期或 null。"
                    )
                ],
            )

    try:
        draft_set, entry = run_extraction(
            get_model(request), original_text, message_date, current_time()
        )
    except (
        ModelUnavailableError,
        ModelTimeoutError,
        ModelOutputInvalidError,
        DraftValidationError,
    ) as exc:
        return _extraction_failure(exc)

    get_cache(request).put(entry)
    # 提取不写 state.json
    return JSONResponse(
        status_code=200, content=draft_set.model_dump(mode="json", by_alias=True)
    )


@router.post("/draft-sets/{draft_set_id}/confirm")
async def confirm_draft_set_endpoint(
    draft_set_id: str, request: Request
) -> JSONResponse:
    # T11：multipart（图片）分支——file 原图 + confirmation JSON 部件
    source_bytes: bytes | None = None
    if _is_multipart(request):
        payload, source_bytes, failure = await _read_multipart_confirmation(request)
        if failure is not None:
            return failure
    else:
        payload = await _read_json_object(request)
        if isinstance(payload, JSONResponse):
            return payload

    # 图片确认：进程内缓存条目是确认链路的必查项（重启即失效）。
    # T11 骨架期条目无草稿 → 用请求级批次视图，共享条目不被改写。
    cache = get_cache(request)
    if source_bytes is not None:
        cache = _skeleton_batch_view(cache, draft_set_id, payload) or cache

    outcome = confirm_draft_set(
        root=request_data_root(request),
        cache=cache,
        draft_set_id=draft_set_id,
        confirmation=payload,
        now=current_time(),
        source_bytes=source_bytes,
    )
    if outcome.error is not None:
        return api_error_response(outcome.error)
    return JSONResponse(status_code=outcome.status_code, content=outcome.body or {})
