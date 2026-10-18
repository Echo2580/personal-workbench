"""首页数据接口：天气、每日段子、随手记。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.security import error_response
from app.modules.home import news as news_service
from app.modules.home import preferences as preferences_service
from app.modules.home import search as search_service
from app.modules.home import services
from app.modules.home.news_model import DeepSeekNewsCurator

router = APIRouter(prefix="/api/v1")


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir)


def _failure(exc: services.HomeServiceError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.status)


def _joke_model(request: Request):
    model = getattr(request.app.state, "joke_model", None)
    if model is None:
        model = DeepSeekJokeModel()
        request.app.state.joke_model = model
    return model


@router.get("/weather")
def get_weather(request: Request, city: str = "南京") -> JSONResponse:
    try:
        payload = services.fetch_weather(city)
    except services.HomeServiceError as exc:
        return _failure(exc)
    return JSONResponse(status_code=200, content=payload)


@router.get("/world-news")
def world_news(request: Request, refresh: str = "0") -> JSONResponse:
    want_refresh = refresh in ("1", "true", "yes")
    model = getattr(request.app.state, "news_model", None)
    if model is None:
        model = DeepSeekNewsCurator()
        request.app.state.news_model = model
    try:
        payload = news_service.build_briefing(_data_dir(request), want_refresh, model)
    except news_service.NewsError as exc:
        return error_response("news_unavailable", exc.message, 503)
    return JSONResponse(status_code=200, content=payload)


@router.get("/notes")
def get_notes(request: Request) -> JSONResponse:
    return JSONResponse(status_code=200, content=services.read_notes(_data_dir(request)))


@router.put("/notes")
async def put_notes(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return error_response("invalid_request", "请求体必须是合法 JSON。", 400)
    if not isinstance(body, dict):
        return error_response("invalid_request", "请求体必须是 JSON 对象。", 400)
    unknown = [key for key in body if key != "lines"]
    if unknown:
        return error_response(
            "invalid_request",
            "包含不可写或未知字段。",
            400,
            details=[{"field": key, "code": "unknown_field", "message": "该字段不可写。"} for key in unknown],
        )
    try:
        payload = services.write_notes(_data_dir(request), body.get("lines"))
    except services.HomeServiceError as exc:
        return _failure(exc)
    return JSONResponse(status_code=200, content=payload)


@router.get("/search")
def global_search(request: Request, q: str = "") -> JSONResponse:
    """全局搜索：项目 / 待办 / 长期任务。"""
    query = (q or "").strip()
    if not query:
        return JSONResponse(status_code=200, content={"query": "", "groups": [], "total": 0})
    if len(query) > 50:
        return error_response("invalid_request", "搜索词不能超过 50 字。", 422)
    projects = None
    service = getattr(request.app.state, "projects", None)
    if service is not None:
        try:
            projects = service.snapshot().get("projects")
        except Exception:  # noqa: BLE001 - 搜索不应因子系统异常整体失败
            projects = None
    payload = search_service.search(
        query,
        Path(request.app.state.data_root),
        projects_snapshot=projects,
    )
    return JSONResponse(status_code=200, content=payload)


@router.get("/preferences")
def get_preferences(request: Request) -> JSONResponse:
    return JSONResponse(status_code=200, content=preferences_service.read_preferences(_data_dir(request)))


@router.put("/preferences")
async def put_preferences(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return error_response("invalid_request", "请求体必须是合法 JSON。", 400)
    if not isinstance(body, dict) or not body:
        return error_response("invalid_request", "请求体必须是非空 JSON 对象。", 400)
    unknown = [key for key in body if key != "city"]
    if unknown:
        return error_response(
            "invalid_request",
            "包含未知字段。",
            400,
            details=[{"field": key, "code": "unknown_field", "message": "该字段不可写。"} for key in unknown],
        )
    try:
        payload = preferences_service.write_preferences(_data_dir(request), body)
    except ValueError:
        return error_response("invalid_request", "city 必须是非空字符串。", 422)
    return JSONResponse(status_code=200, content=payload)
