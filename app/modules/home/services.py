"""首页数据服务：真实天气与随手记落盘。

这些是首页专用服务，不对应导航模块：ModuleDefinition 的 route 为 None，
外壳导航会跳过「可用但无路由」的模块，因此只暴露 /api/v1/* 接口。

天气：Open-Meteo（免密钥），按城市查询当前天气与逐小时温度，进程内缓存 10 分钟。
随手记：<data_dir>/home/notes.json，GET 读取、PUT 覆盖。
"""

from __future__ import annotations

import json
import threading
import uuid
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

SHANGHAI = timezone(timedelta(hours=8))

WEATHER_CACHE_SECONDS = 600
WEATHER_TIMEOUT = 8.0
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# 常用城市坐标兜底（网络失败时仍能给出可用坐标，但天气本身必须实时）
CITY_FALLBACK: dict[str, tuple[float, float]] = {
    "南京": (32.0603, 118.7969),
    "杭州": (30.2741, 120.1551),
    "苏州": (31.2989, 120.5853),
    "上海": (31.2304, 121.4737),
}

WEATHER_CODES = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "轻微毛毛雨",
    53: "毛毛雨",
    55: "浓毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "强阵雨",
    82: "暴雨",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "强雷暴伴冰雹",
}

_weather_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_weather_lock = threading.Lock()


class HomeServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _home_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "home"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _condition(code: Any) -> str:
    try:
        return WEATHER_CODES.get(int(code), "天气未知")
    except (TypeError, ValueError):
        return "天气未知"


def _geocode(client: httpx.Client, city: str) -> tuple[float, float]:
    if city in CITY_FALLBACK:
        return CITY_FALLBACK[city]
    try:
        response = client.get(
            GEOCODE_URL,
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if results:
            return float(results[0]["latitude"]), float(results[0]["longitude"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    raise HomeServiceError("city_not_found", f"找不到城市「{city}」的坐标。", 404)


def fetch_weather(city: str) -> dict[str, Any]:
    city = (city or "").strip() or "南京"
    now = time.time()
    with _weather_lock:
        cached = _weather_cache.get(city)
        if cached and now - cached[0] < WEATHER_CACHE_SECONDS:
            return {**cached[1], "cached": True}

    try:
        with httpx.Client(timeout=WEATHER_TIMEOUT) as client:
            latitude, longitude = _geocode(client, city)
            response = client.get(
                FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m",
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "hourly": "temperature_2m",
                    "timezone": "Asia/Shanghai",
                    "forecast_days": 2,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise HomeServiceError("weather_unavailable", "天气服务暂时不可用。", 503) from exc
    except ValueError as exc:
        raise HomeServiceError("weather_unavailable", "天气服务返回了无法解析的数据。", 503) from exc

    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    hourly = payload.get("hourly") or {}
    try:
        temperature = float(current["temperature_2m"])
        high = float((daily.get("temperature_2m_max") or [None])[0])
        low = float((daily.get("temperature_2m_min") or [None])[0])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise HomeServiceError("weather_unavailable", "天气数据不完整。", 503) from exc

    hourly_times = hourly.get("time") or []
    hourly_temps = hourly.get("temperature_2m") or []
    now_iso = datetime.now(SHANGHAI).strftime("%Y-%m-%dT%H:00")
    forecast: list[dict[str, Any]] = []
    for index, moment in enumerate(hourly_times):
        if not isinstance(moment, str) or moment <= now_iso:
            continue
        try:
            value = round(float(hourly_temps[index]))
        except (IndexError, TypeError, ValueError):
            continue
        forecast.append({"time": moment[11:16], "temperature": value})
        if len(forecast) == 4:
            break

    result = {
        "city": city,
        "temperature": round(temperature),
        "condition": _condition(current.get("weather_code")),
        "high": round(high),
        "low": round(low),
        "humidity": current.get("relative_humidity_2m"),
        "wind": current.get("wind_speed_10m"),
        "forecast": forecast,
        "fetchedAt": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "cached": False,
    }
    with _weather_lock:
        _weather_cache[city] = (now, result)
    return result


# ---------------------------------------------------------------- 随手记

MAX_NOTES = 200
MAX_NOTE_TEXT = 500


def _notes_path(data_dir: Path) -> Path:
    return _home_dir(data_dir) / "notes.json"


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _normalise_note(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    note_id = raw.get("id")
    if not isinstance(note_id, str) or not note_id:
        note_id = uuid.uuid4().hex[:12]
    created = raw.get("createdAt")
    if not isinstance(created, str) or not created:
        created = _now_iso()
    return {"id": note_id, "text": text.strip()[:MAX_NOTE_TEXT], "createdAt": created}


def _load_notes(data_dir: Path) -> list[dict]:
    payload = _read_json(_notes_path(data_dir)) or {}
    items = payload.get("items")
    if isinstance(items, list):
        return [note for note in (_normalise_note(raw) for raw in items) if note]
    # 兼容旧版 {lines: [...]}：按行迁移成独立笔记
    lines = payload.get("lines")
    if isinstance(lines, list):
        stamp = _now_iso()
        migrated = []
        for line in lines:
            if isinstance(line, str) and line.strip():
                migrated.append(
                    {"id": uuid.uuid4().hex[:12], "text": line.strip()[:MAX_NOTE_TEXT], "createdAt": stamp}
                )
        return migrated
    return []


def _save_notes(data_dir: Path, items: list[dict]) -> None:
    path = _notes_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": items[:MAX_NOTES], "updatedAt": _now_iso()}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _clean_note_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HomeServiceError("invalid_request", "笔记内容不能为空。", 422)
    text = " ".join(value.split())
    if len(text) > MAX_NOTE_TEXT:
        raise HomeServiceError("invalid_request", f"单条笔记不能超过 {MAX_NOTE_TEXT} 字。", 422)
    return text


def read_notes(data_dir: Path) -> dict:
    return {"items": _load_notes(data_dir)}


def add_note(data_dir: Path, text: object) -> dict:
    cleaned = _clean_note_text(text)
    items = _load_notes(data_dir)
    note = {"id": uuid.uuid4().hex[:12], "text": cleaned, "createdAt": _now_iso()}
    items.insert(0, note)
    _save_notes(data_dir, items)
    return {"item": note}


def update_note(data_dir: Path, note_id: str, text: object) -> dict:
    cleaned = _clean_note_text(text)
    items = _load_notes(data_dir)
    for note in items:
        if note["id"] == note_id:
            note["text"] = cleaned
            _save_notes(data_dir, items)
            return {"item": note}
    raise HomeServiceError("note_not_found", "这条笔记不存在或已被删除。", 404)


def delete_note(data_dir: Path, note_id: str) -> None:
    items = _load_notes(data_dir)
    remaining = [note for note in items if note["id"] != note_id]
    if len(remaining) == len(items):
        raise HomeServiceError("note_not_found", "这条笔记不存在或已被删除。", 404)
    _save_notes(data_dir, remaining)
