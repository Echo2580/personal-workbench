"""数据备份与恢复：工作台用户数据的导出、恢复与概览。

备份范围（用户内容）：
- tasks/state.json（任务、来源、长期目标、草稿、提醒状态）
- home/preferences.json、home/notes.json、home/news_briefing.json
- settings.toml、projects.toml
- history/*.json

不备份：logs/、cache/、esbuild/、runtime/、news.json（可重新抓取）、AI 密钥（在系统环境变量里）。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import tomllib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.modules.tasks.storage import load_snapshot

FORMAT = "personal-workbench-backup"
FORMAT_VERSION = 1
SHANGHAI = timezone(timedelta(hours=8))
MAX_RESTORE_BYTES = 20 * 1024 * 1024
MAX_AUTO_BACKUPS = 10

HOME_FILES = {
    "preferences": "preferences.json",
    "notes": "notes.json",
    "newsBriefing": "news_briefing.json",
}


class BackupError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_backup"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(SHANGHAI)


def _stamp() -> str:
    return _now().strftime("%Y%m%d-%H%M%S")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _read_json(path: Path) -> Any:
    text = _read_text(path)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".restore-tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def collect_bundle(data_dir: Path, app_version: str) -> dict:
    data_dir = Path(data_dir)
    tasks_state = _read_json(data_dir / "tasks" / "state.json")
    home: dict[str, Any] = {}
    for key, filename in HOME_FILES.items():
        home[key] = _read_json(data_dir / "home" / filename)
    history: dict[str, str] = {}
    history_dir = data_dir / "history"
    if history_dir.is_dir():
        for item in sorted(history_dir.glob("*.json"))[:50]:
            text = _read_text(item)
            if text and len(text) <= 1_000_000:
                history[item.name] = text
    return {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "exportedAt": _now().isoformat(timespec="seconds"),
        "appVersion": app_version,
        "data": {
            "tasksState": tasks_state,
            "home": home,
            "settingsToml": _read_text(data_dir / "settings.toml"),
            "projectsToml": _read_text(data_dir / "projects.toml"),
            "history": history,
        },
    }


def export_filename() -> str:
    return f"personal-workbench-backup-{_stamp()}.json"


def _validate_bundle(bundle: Any) -> dict:
    if not isinstance(bundle, dict):
        raise BackupError("备份文件必须是 JSON 对象。")
    if bundle.get("format") != FORMAT:
        raise BackupError("不是个人工作台的备份文件。")
    version = bundle.get("formatVersion")
    if not isinstance(version, int) or version < 1 or version > FORMAT_VERSION:
        raise BackupError(f"备份格式版本不受支持：{version!r}。")
    data = bundle.get("data")
    if not isinstance(data, dict):
        raise BackupError("备份文件缺少 data 内容。")

    tasks_state = data.get("tasksState")
    if tasks_state is not None and not isinstance(tasks_state, dict):
        raise BackupError("任务数据格式不正确。")

    home = data.get("home", {})
    if not isinstance(home, dict):
        raise BackupError("首页数据格式不正确。")
    for key in HOME_FILES:
        value = home.get(key)
        if value is not None and not isinstance(value, dict):
            raise BackupError(f"首页数据 {key} 格式不正确。")

    for key in ("settingsToml", "projectsToml"):
        text = data.get(key, "")
        if not isinstance(text, str):
            raise BackupError(f"{key} 必须是字符串。")
        if text.strip():
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                raise BackupError(f"{key} 不是合法的 TOML：{exc}") from exc

    history = data.get("history", {})
    if not isinstance(history, dict):
        raise BackupError("history 格式不正确。")
    for name, text in history.items():
        if not isinstance(name, str) or not isinstance(text, str):
            raise BackupError("history 内容格式不正确。")
        if "/" in name or "\\" in name or name.startswith("."):
            raise BackupError("history 文件名不合法。")
        try:
            json.loads(text)
        except ValueError as exc:
            raise BackupError(f"history/{name} 不是合法 JSON。") from exc

    if tasks_state is not None:
        _validate_tasks_state(tasks_state)
    return data


def _validate_tasks_state(tasks_state: dict) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="wb-restore-check-"))
    try:
        (temp_root / "state.json").write_text(_dump_json(tasks_state), encoding="utf-8")
        loaded = load_snapshot(temp_root)
        if loaded.error is not None or loaded.snapshot is None:
            raise BackupError("任务数据无法读取（可能损坏或版本不兼容）。", 422, "invalid_tasks_state")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _auto_backup(data_dir: Path, app_version: str) -> Path:
    backup_dir = Path(data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"auto-{_stamp()}.json"
    target.write_text(_dump_json(collect_bundle(data_dir, app_version)), encoding="utf-8")
    files = sorted(backup_dir.glob("auto-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in files[MAX_AUTO_BACKUPS:]:
        stale.unlink(missing_ok=True)
    return target


def restore_bundle(data_dir: Path, bundle: Any, projects, app_version: str) -> dict:
    data_dir = Path(data_dir)
    data = _validate_bundle(bundle)

    auto_path = _auto_backup(data_dir, app_version)
    try:
        tasks_state = data.get("tasksState")
        tasks_file = data_dir / "tasks" / "state.json"
        if tasks_state is not None:
            _write_text_atomic(tasks_file, _dump_json(tasks_state))

        home = data.get("home", {})
        for key, filename in HOME_FILES.items():
            value = home.get(key)
            if value is not None:
                _write_text_atomic(data_dir / "home" / filename, _dump_json(value))

        if data.get("settingsToml"):
            _write_text_atomic(data_dir / "settings.toml", data["settingsToml"])
        if data.get("projectsToml"):
            _write_text_atomic(data_dir / "projects.toml", data["projectsToml"])

        history = data.get("history") or {}
        if history:
            (data_dir / "history").mkdir(parents=True, exist_ok=True)
            for name, text in history.items():
                _write_text_atomic(data_dir / "history" / name, text)

        if projects is not None:
            projects.safe_refresh()
    except BackupError:
        raise
    except Exception as exc:  # noqa: BLE001 - 恢复失败时回滚
        rollback = json.loads(auto_path.read_text(encoding="utf-8"))
        try:
            _apply_bundle_without_validation(data_dir, rollback.get("data", {}))
            if projects is not None:
                projects.safe_refresh()
        except Exception:  # noqa: BLE001 - 回滚尽力而为
            pass
        raise BackupError(f"恢复失败，已尝试回滚：{exc}", 500, "restore_failed") from exc

    return {
        "restored": True,
        "restoredAt": _now().isoformat(timespec="seconds"),
        "autoBackup": auto_path.name,
        "summary": _summarise(data_dir, projects),
    }


def _apply_bundle_without_validation(data_dir: Path, data: dict) -> None:
    tasks_state = data.get("tasksState")
    if isinstance(tasks_state, dict):
        _write_text_atomic(data_dir / "tasks" / "state.json", _dump_json(tasks_state))
    home = data.get("home") or {}
    for key, filename in HOME_FILES.items():
        value = home.get(key)
        if isinstance(value, dict):
            _write_text_atomic(data_dir / "home" / filename, _dump_json(value))
    for key, filename in (("settingsToml", "settings.toml"), ("projectsToml", "projects.toml")):
        text = data.get(key)
        if isinstance(text, str) and text.strip():
            _write_text_atomic(data_dir / key, text)


def _summarise(data_dir: Path, projects) -> dict:
    snapshot_tasks = snapshot_goals = snapshot_sources = 0
    loaded = load_snapshot(Path(data_dir) / "tasks")
    if loaded.snapshot is not None:
        snapshot_tasks = len(loaded.snapshot.tasks)
        snapshot_goals = len(loaded.snapshot.goals)
        snapshot_sources = len(loaded.snapshot.sources)
    notes = _read_json(Path(data_dir) / "home" / "notes.json") or {}
    note_count = len(notes.get("items") or []) if isinstance(notes, dict) else 0
    project_count = 0
    if projects is not None:
        try:
            project_count = len(projects.snapshot().get("projects") or [])
        except Exception:  # noqa: BLE001 - 概览不应因项目服务异常失败
            project_count = 0
    return {
        "tasks": snapshot_tasks,
        "goals": snapshot_goals,
        "sources": snapshot_sources,
        "notes": note_count,
        "projects": project_count,
    }


def collect_info(data_dir: Path, projects, app_version: str) -> dict:
    data_dir = Path(data_dir)
    backups = []
    backup_dir = data_dir / "backups"
    if backup_dir.is_dir():
        for item in sorted(backup_dir.glob("auto-*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
            stat = item.stat()
            backups.append(
                {
                    "name": item.name,
                    "size": stat.st_size,
                    "createdAt": datetime.fromtimestamp(stat.st_mtime, SHANGHAI).isoformat(timespec="seconds"),
                }
            )
    return {
        "dataDir": str(data_dir),
        "appVersion": app_version,
        "summary": _summarise(data_dir, projects),
        "backups": backups[:MAX_AUTO_BACKUPS],
    }


def new_instance_note() -> str:
    """占位：保持模块导入稳定（恢复后可提示重启）。"""
    return uuid.uuid4().hex
