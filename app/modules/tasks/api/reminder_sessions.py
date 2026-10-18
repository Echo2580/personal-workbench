"""Reminder session endpoints (契约 §4 / §4.3 / §6)."""

from __future__ import annotations

import re
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
from app.modules.tasks.services.reminder_runtime import (
    SessionRegistry,
    acknowledge_reminder,
    due_reminders,
    open_session,
)


router = APIRouter()

_REQUIRED_ACK_KEYS = ("sessionId", "reminderVersion")
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


def get_session_registry(request: Request) -> SessionRegistry:
    """Per-app-instance registry; a restart yields an empty one (404 语义)."""
    registry = getattr(request.app.state, "reminder_sessions", None)
    if registry is None:
        registry = SessionRegistry()
        request.app.state.reminder_sessions = registry
    return registry


async def _read_json_object(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return error_response(400, "invalid_request", "请求体必须是合法 JSON。")
    if not isinstance(payload, dict):
        return error_response(400, "invalid_request", "请求体必须是 JSON 对象。")
    return payload


def _valid_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_PATTERN.fullmatch(value))


def _ack_request_error(payload: dict[str, Any]) -> JSONResponse | None:
    unknown = [key for key in payload if key not in _REQUIRED_ACK_KEYS]
    if unknown:
        return error_response(
            400,
            "invalid_request",
            "包含不可写或未知字段。",
            field_errors=[
                FieldError(key, "unknown_field", "该字段不可写或不存在。")
                for key in unknown
            ],
        )
    missing = [key for key in _REQUIRED_ACK_KEYS if key not in payload]
    if missing:
        return error_response(
            400,
            "invalid_request",
            "确认请求必须同时包含 sessionId 与 reminderVersion。",
            field_errors=[FieldError(key, "missing", "缺少必填键。") for key in missing],
        )
    invalid = [key for key in _REQUIRED_ACK_KEYS if not _valid_uuid(payload[key])]
    if invalid:
        return error_response(
            400,
            "invalid_request",
            "sessionId 与 reminderVersion 必须是规范小写 UUID。",
            field_errors=[
                FieldError(key, "invalid_uuid", "必须是规范小写 UUID。")
                for key in invalid
            ],
        )
    return None


@router.post("/reminder-sessions")
async def create_reminder_session(request: Request) -> JSONResponse:
    outcome = open_session(
        request_data_root(request), get_session_registry(request), current_time()
    )
    if outcome.error is not None:
        return api_error_response(outcome.error)
    return JSONResponse(status_code=200, content=outcome.body or {})


@router.get("/reminder-sessions/{session_id}/due")
async def get_due_reminders(session_id: str, request: Request) -> JSONResponse:
    outcome = due_reminders(
        request_data_root(request),
        get_session_registry(request),
        session_id,
        current_time(),
    )
    if outcome.error is not None:
        return api_error_response(outcome.error)
    return JSONResponse(status_code=200, content=outcome.body or {})


@router.post("/reminders/{task_id}/acknowledgment")
async def acknowledge_reminder_endpoint(
    task_id: str, request: Request
) -> JSONResponse:
    payload = await _read_json_object(request)
    if isinstance(payload, JSONResponse):
        return payload

    failure = _ack_request_error(payload)
    if failure is not None:
        return failure

    outcome = acknowledge_reminder(
        request_data_root(request),
        get_session_registry(request),
        task_id,
        payload["sessionId"],
        payload["reminderVersion"],
        current_time(),
    )
    if outcome.error is not None:
        return api_error_response(outcome.error)
    return JSONResponse(status_code=outcome.status_code, content=outcome.body or {})
