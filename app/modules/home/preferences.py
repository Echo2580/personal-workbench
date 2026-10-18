"""首页偏好设置：天气城市、自定义快速入口、首页大字与个人资料。

落盘到 <data_dir>/home/preferences.json；服务端权威，读取时的非法值退回默认。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

DEFAULT_CITY = "南京"
DEFAULT_HEADLINE = ""
DEFAULT_DISPLAY_NAME = "林同学"
DEFAULT_SIGNATURE = "个人版"
MAX_CITY_LENGTH = 30
MAX_ENTRIES = 8
MAX_LABEL = 20
MAX_URL = 500
MAX_HEADLINE_LENGTH = 30
MAX_DISPLAY_NAME_LENGTH = 20
MAX_SIGNATURE_LENGTH = 40
URL_PATTERN = re.compile(r"^https?://[^\s]+$")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
WRITABLE_FIELDS = {"city", "quickEntries", "heroHeadline", "profile"}
PROFILE_FIELDS = {"displayName", "signature"}


def _default_profile() -> dict:
    return {"displayName": DEFAULT_DISPLAY_NAME, "signature": DEFAULT_SIGNATURE}


DEFAULT_PREFERENCES: dict = {
    "city": DEFAULT_CITY,
    "quickEntries": [],
    "heroHeadline": DEFAULT_HEADLINE,
    "profile": _default_profile(),
}


class PreferencesError(ValueError):
    """偏好校验失败；message 直接给前端。"""


def _home_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "home"


def _read_json(path: Path) -> dict | None:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _single_line(
    value: object, field: str, *, max_length: int, allow_empty: bool
) -> str:
    """写入校验：单行、禁止控制字符、长度上限（超长直接拒绝而不是静默截断）。"""
    if not isinstance(value, str):
        raise PreferencesError(f"{field} 必须是字符串。")
    if CONTROL_CHARACTERS.search(value):
        raise PreferencesError(f"{field} 不能包含换行或控制字符。")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise PreferencesError(f"{field} 最多 {max_length} 个字符。")
    if not allow_empty and not cleaned:
        raise PreferencesError(f"{field} 不能为空。")
    return cleaned


def _read_single_line(
    value: object, *, max_length: int, allow_empty: bool, fallback: str
) -> str:
    """读取容错：非法存量值退回默认，避免坏数据让首页/外壳整体失败。"""
    if not isinstance(value, str) or CONTROL_CHARACTERS.search(value):
        return fallback
    cleaned = value.strip()
    if len(cleaned) > max_length:
        return fallback
    if not allow_empty and not cleaned:
        return fallback
    return cleaned


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


def _read_headline(value: object) -> str:
    return _read_single_line(
        value,
        max_length=MAX_HEADLINE_LENGTH,
        allow_empty=True,
        fallback=DEFAULT_HEADLINE,
    )


def _read_profile(value: object) -> dict:
    profile = _default_profile()
    if not isinstance(value, dict):
        return profile
    profile["displayName"] = _read_single_line(
        value.get("displayName"),
        max_length=MAX_DISPLAY_NAME_LENGTH,
        allow_empty=False,
        fallback=DEFAULT_DISPLAY_NAME,
    )
    profile["signature"] = _read_single_line(
        value.get("signature"),
        max_length=MAX_SIGNATURE_LENGTH,
        allow_empty=True,
        fallback=DEFAULT_SIGNATURE,
    )
    return profile


def read_preferences(data_dir: Path) -> dict:
    payload = _read_json(_home_dir(data_dir) / "preferences.json") or {}
    city = payload.get("city")
    if not isinstance(city, str) or not city.strip():
        city = DEFAULT_CITY
    entries = payload.get("quickEntries")
    if not isinstance(entries, list):
        entries = []
    return {
        "city": city.strip()[:MAX_CITY_LENGTH],
        "quickEntries": [item for item in entries if isinstance(item, dict)],
        "heroHeadline": _read_headline(payload.get("heroHeadline")),
        "profile": _read_profile(payload.get("profile")),
    }


def write_preferences(data_dir: Path, payload: dict) -> dict:
    """部分更新：city / quickEntries / heroHeadline / profile 任传其一或都传，未传的保持不变。

    profile 支持字段级部分更新（只传 displayName 或 signature 时合并）。
    """
    if not isinstance(payload, dict) or not payload:
        raise PreferencesError("请求体必须是非空对象。")
    unknown = [key for key in payload if key not in WRITABLE_FIELDS]
    if unknown:
        raise PreferencesError(f"包含未知字段：{'、'.join(unknown)}。")
    current = read_preferences(data_dir)
    if "city" in payload:
        current["city"] = _clean_city(payload["city"])
    if "quickEntries" in payload:
        current["quickEntries"] = _clean_entries(payload["quickEntries"])
    if "heroHeadline" in payload:
        current["heroHeadline"] = _single_line(
            payload["heroHeadline"],
            "heroHeadline",
            max_length=MAX_HEADLINE_LENGTH,
            allow_empty=True,
        )
    if "profile" in payload:
        patch = payload["profile"]
        if not isinstance(patch, dict):
            raise PreferencesError("profile 必须是对象。")
        unknown_profile = [key for key in patch if key not in PROFILE_FIELDS]
        if unknown_profile:
            raise PreferencesError(f"profile 包含未知字段：{'、'.join(unknown_profile)}。")
        profile = dict(current["profile"])
        if "displayName" in patch:
            profile["displayName"] = _single_line(
                patch["displayName"],
                "显示名",
                max_length=MAX_DISPLAY_NAME_LENGTH,
                allow_empty=False,
            )
        if "signature" in patch:
            profile["signature"] = _single_line(
                patch["signature"],
                "签名",
                max_length=MAX_SIGNATURE_LENGTH,
                allow_empty=True,
            )
        current["profile"] = profile
    _write_json(_home_dir(data_dir) / "preferences.json", current)
    return current
