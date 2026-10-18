"""Strict model configuration and scalar format checks shared by T04-B entities."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Final

from pydantic import BaseModel, ConfigDict


_UUID_PATTERN: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_SHA256_PATTERN: Final = re.compile(r"[0-9a-fA-F]{64}\Z")
_DATE_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DATETIME_PATTERN: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+08:00\Z"
)


class StrictModel(BaseModel):
    """Strict, no-extra base model used by every T04-B entity."""

    model_config = ConfigDict(extra="forbid", strict=True)


def validate_uuid(value: str, field_name: str) -> str:
    if not _UUID_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase standard UUID")
    return value


def validate_optional_uuid(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return validate_uuid(value, field_name)


def validate_sha256(value: str, field_name: str) -> str:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a 64-character hex string")
    return value


def validate_optional_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not _DATE_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a real calendar date") from exc
    return value


def validate_timestamp(value: str, field_name: str) -> str:
    """Return the input string unchanged after format validation."""
    if not _DATETIME_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be RFC 3339 with +08:00 offset")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid local date and time") from exc
    if parsed.utcoffset() != timedelta(hours=8):
        raise ValueError(f"{field_name} must use +08:00 offset")
    return value


def validate_optional_timestamp(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return validate_timestamp(value, field_name)


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
