"""首页偏好设置：目前只有天气城市，落盘到 <data_dir>/home/preferences.json。"""

from pathlib import Path

DEFAULT_CITY = "南京"
MAX_CITY_LENGTH = 30


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


def read_preferences(data_dir: Path) -> dict:
    payload = _read_json(_home_dir(data_dir) / "preferences.json") or {}
    city = payload.get("city")
    if not isinstance(city, str) or not city.strip():
        city = DEFAULT_CITY
    return {"city": city.strip()[:MAX_CITY_LENGTH]}


def write_preferences(data_dir: Path, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("invalid")
    city = payload.get("city")
    if not isinstance(city, str) or not city.strip():
        raise ValueError("city 必须是非空字符串。")
    cleaned = city.strip()[:MAX_CITY_LENGTH]
    result = {"city": cleaned}
    _write_json(_home_dir(data_dir) / "preferences.json", result)
    return result
