"""首页数据服务：真实天气与随手记落盘。

这些是首页专用服务，不对应导航模块：ModuleDefinition 的 route 为 None，
外壳导航会跳过「可用但无路由」的模块，因此只暴露 /api/v1/* 接口。

天气：Open-Meteo（免密钥），按城市查询当前天气与逐小时温度，进程内缓存 10 分钟。
随手记：<data_dir>/home/notes.json，GET 读取、PUT 覆盖。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
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

# 地理编码：中文短名常与外地乡镇重名（「洛阳」会先命中福建洛阳镇），
# 因此同时查原名和「原名+市」，按名称匹配/人口挑候选；还不够像城市时用拼音兜底。
GEOCODE_COUNT = 20
CITY_POPULATION_HINT = 100_000
_PLACE_SUFFIXES = ("市", "县", "区", "旗", "盟", "镇", "乡")

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


def _is_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _normalise_place_name(name: object) -> str:
    """去掉行政区划后缀再比较，让「洛阳」与「洛阳市」算同一个名字。"""
    text = str(name or "").strip()
    for suffix in _PLACE_SUFFIXES:
        if len(text) > len(suffix) and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _population_of(item: dict[str, Any]) -> int:
    try:
        return int(item.get("population") or 0)
    except (TypeError, ValueError):
        return 0


def _search_geocode(client: httpx.Client, name: str, language: str = "zh") -> list[dict[str, Any]]:
    response = client.get(
        GEOCODE_URL,
        params={"name": name, "count": GEOCODE_COUNT, "language": language, "format": "json"},
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    return [
        item
        for item in results
        if isinstance(item, dict)
        and isinstance(item.get("latitude"), (int, float))
        and isinstance(item.get("longitude"), (int, float))
    ]


def _pick_city_candidate(candidates: list[dict[str, Any]], city: str) -> dict[str, Any] | None:
    """名称匹配优先，其次人口，最后国内结果；避免被同名乡镇/邻市挤掉。"""
    target = _normalise_place_name(city)

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        exact = 1 if _normalise_place_name(item.get("name")) == target else 0
        return (exact, _population_of(item), 1 if item.get("country_code") == "CN" else 0)

    return max(candidates, key=score) if candidates else None


def _pick_by_relevance(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """拼音查询按 Open-Meteo 相关度排序返回；优先国内结果，避免同名国外城市。"""
    if not candidates:
        return None
    for item in candidates:
        if item.get("country_code") == "CN":
            return item
    return candidates[0]


def _pinyin_name(city: str) -> str:
    """中文转无音调拼音（「信阳」→ xinyang）；依赖缺失时返回空串，退化为原名查询。"""
    try:
        from pypinyin import lazy_pinyin
    except Exception:  # noqa: BLE001 - 可选依赖缺失不阻塞天气
        return ""
    try:
        return "".join(lazy_pinyin(city, errors="ignore")).strip()
    except Exception:  # noqa: BLE001 - 拼音库异常不阻塞天气
        return ""


def _geocode(client: httpx.Client, city: str) -> tuple[float, float]:
    if city in CITY_FALLBACK:
        return CITY_FALLBACK[city]

    queries = [city]
    if _is_chinese(city) and not city.endswith(_PLACE_SUFFIXES):
        queries.append(city + "市")
    try:
        candidates: list[dict[str, Any]] = []
        for query in queries:
            candidates.extend(_search_geocode(client, query))
    except httpx.HTTPError as exc:
        raise HomeServiceError("weather_unavailable", "天气服务暂时不可用。", 503) from exc

    if _is_chinese(city):
        best = _pick_city_candidate(candidates, city)
        # 中文索引里有些城市缺失（如「信阳」「昆山」），人口不像城市时再用拼音查一次。
        if _population_of(best or {}) < CITY_POPULATION_HINT:
            pinyin_query = _pinyin_name(city)
            if pinyin_query and pinyin_query.lower() != city.lower():
                try:
                    pinyin_candidates = _search_geocode(client, pinyin_query)
                except httpx.HTTPError:
                    pinyin_candidates = []
                pinyin_best = _pick_by_relevance(pinyin_candidates)
                if pinyin_best is not None and _population_of(pinyin_best) > _population_of(
                    best or {}
                ):
                    best = pinyin_best
    else:
        # 英文名按 Open-Meteo 相关度取第一条（例如 Luoyang 第一条就是河南洛阳）。
        best = candidates[0] if candidates else None

    if best is not None:
        return float(best["latitude"]), float(best["longitude"])
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
MAX_NOTE_TEXT = 1000


def _notes_path(data_dir: Path) -> Path:
    return _home_dir(data_dir) / "notes.json"


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _legacy_note_id(index: int, text: str) -> str:
    # Read-only compatibility: repeated reads must resolve the same deep link.
    # The position distinguishes duplicate lines; mutations persist these IDs.
    return uuid.uuid5(uuid.NAMESPACE_URL, f"personal-workbench/note/{index}/{text}").hex[:12]


def _note_text_lines(value: object) -> str | None:
    """把笔记文本规范化：统一换行、保留行内空格、去掉首尾空白；无效时返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    # 除换行外的控制字符统一替换为空格（避免 JSON/前端出现不可见控制符）。
    text = "".join(" " if (ord(ch) < 32 and ch != "\n") else ch for ch in text)
    text = text.strip()
    return text or None


def _normalise_note(raw: object, index: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = _note_text_lines(raw.get("text"))
    if text is None:
        return None
    note_id = raw.get("id")
    if not isinstance(note_id, str) or not note_id:
        note_id = _legacy_note_id(index, text)
    created = raw.get("createdAt")
    if not isinstance(created, str) or not created:
        created = _now_iso()
    return {"id": note_id, "text": text[:MAX_NOTE_TEXT], "createdAt": created}


def _load_notes(data_dir: Path) -> list[dict]:
    payload = _read_json(_notes_path(data_dir)) or {}
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return [note for note in (_normalise_note(raw, index) for index, raw in enumerate(items)) if note]
    # 兼容旧版 {lines: [...]}：按行迁移成独立笔记
    lines = payload.get("lines")
    if isinstance(lines, list):
        stamp = _now_iso()
        migrated = []
        for index, line in enumerate(lines):
            text = _note_text_lines(line)
            if text is not None:
                migrated.append(
                    {"id": _legacy_note_id(index, text), "text": text[:MAX_NOTE_TEXT], "createdAt": stamp}
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
    text = _note_text_lines(value)
    if text is None:
        raise HomeServiceError("invalid_request", "笔记内容不能为空。", 422)
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
