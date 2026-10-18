"""首页数据接口：天气、每日段子、随手记。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.security import error_response
from app.modules.home import services
from app.modules.home.joke_model import DeepSeekJokeModel

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


@router.get("/daily-joke")
def get_daily_joke(request: Request, refresh: str = "0") -> JSONResponse:
    want_refresh = refresh in ("1", "true", "yes")
    try:
        payload = services.get_daily_joke(_data_dir(request), want_refresh, _joke_model(request))
    except services.HomeServiceError as exc:
        return _failure(exc)
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
