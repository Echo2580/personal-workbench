"""首页偏好设置：天气城市与自定义快速入口，落盘到 <data_dir>/home/preferences.json。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

DEFAULT_CITY = "南京"
MAX_CITY_LENGTH = 30
MAX_ENTRIES = 8
MAX_LABEL = 20
MAX_URL = 500
URL_PATTERN = re.compile(r"^https?://[^\s]+$")

DEFAULT_PREFERENCES: dict = {"city": DEFAULT_CITY, "quickEntries": []}


class PreferencesError(ValueError):
    """偏好校验失败；message 直接给前端。"""


def _home_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "home"


def _read_json(path: Path) -> dict | None:
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write_json(path: Path, payload: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _clean_city(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreferencesError("city 必须是非空字符串。")
    return value.strip()[:MAX_CITY_LENGTH]


def _clean_entries(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise PreferencesError("quickEntries 必须是数组。")
    if len(value) > MAX_ENTRIES:
        raise PreferencesError(f"自定义入口最多 {MAX_ENTRIES} 个。")
    cleaned: list[dict] = []
    seen_urls: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise PreferencesError("每个入口必须是对象。")
        label = item.get("label")
        url = item.get("url")
        if not isinstance(label, str) or not label.strip():
            raise PreferencesError("入口名称不能为空。")
        label = label.strip()[:MAX_LABEL]
        if not isinstance(url, str) or not URL_PATTERN.match(url.strip()):
            raise PreferencesError("入口地址必须是 http(s) 链接。")
        url = url.strip()[:MAX_URL]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        entry_id = item.get("id")
        if not isinstance(entry_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", entry_id):
            entry_id = uuid.uuid4().hex[:12]
        cleaned.append({"id": entry_id, "label": label, "url": url})
    return cleaned


def read_preferences(data_dir: Path) -> dict:
    payload = _read_json(_home_dir(data_dir) / "preferences.json") or {}
    city = payload.get("city")
    if not isinstance(city, str) or not city.strip():
        city = DEFAULT_CITY
    entries = payload.get("quickEntries")
    if not isinstance(entries, list):
        entries = []
    return {"city": city.strip()[:MAX_CITY_LENGTH], "quickEntries": [item for item in entries if isinstance(item, dict)]}


def write_preferences(data_dir: Path, payload: dict) -> dict:
    """部分更新：city / quickEntries 任传其一或都传，未传的保持不变。"""
    if not isinstance(payload, dict) or not payload:
        raise PreferencesError("请求体必须是非空对象。")
    unknown = [key for key in payload if key not in {"city", "quickEntries"}]
    if unknown:
        raise PreferencesError(f"包含未知字段：{'、'.join(unknown)}。")
    current = read_preferences(data_dir)
    if "city" in payload:
        current["city"] = _clean_city(payload["city"])
    if "quickEntries" in payload:
        current["quickEntries"] = _clean_entries(payload["quickEntries"])
    _write_json(_home_dir(data_dir) / "preferences.json", current)
    return current
