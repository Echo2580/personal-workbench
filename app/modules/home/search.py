"""全局搜索：项目、待办、长期任务、随手记。

数据直接读各自模块的现有存储，不引入新的索引：
- 项目：ProjectService.snapshot()（内存/磁盘最新扫描结果）
- 待办与长期任务：待办模块的 state.json（load_snapshot）
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.tasks.storage import load_snapshot
from app.modules.home import services

GROUP_LIMIT = 5
QUERY_MAX = 50


def _friendly_when(value: str | None) -> str:
    if not value:
        return "未排期"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{moment.month}/{moment.day} {moment.hour:02d}:{moment.minute:02d}"


def _matches(text: str | None, query: str) -> bool:
    return bool(text) and query in text.casefold()


def _project_items(projects: Any, query: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(projects, list):
        return items
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = project.get("name") or project.get("default_name") or ""
        path = project.get("path") or ""
        if not (_matches(name, query) or _matches(path, query)):
            continue
        items.append(
            {
                "title": name or path,
                "subtitle": path,
                "kind": "project",
                "route": "/projects",
                "badge": project.get("type") or "",
            }
        )
        if len(items) >= GROUP_LIMIT:
            break
    return items


def _task_items(data_root: Path, query: str, limit: int = GROUP_LIMIT) -> list[dict[str, Any]]:
    loaded = load_snapshot(Path(data_root))
    if loaded.error is not None or loaded.snapshot is None:
        return []
    items: list[dict[str, Any]] = []
    for task in loaded.snapshot.tasks.values():
        if not _matches(task.title, query):
            continue
        due = (task.due_time.resolved_value if task.due_time else None) or (
            task.start_time.resolved_value if task.start_time else None
        )
        items.append(
            {
                "title": task.title,
                "subtitle": _friendly_when(due),
                "kind": "task",
                "route": "/tasks",
                "badge": "已完成" if task.status == "completed" else "待办",
            }
        )
        if len(items) >= limit:
            break
    return items


def _goal_items(data_root: Path, query: str) -> list[dict[str, Any]]:
    loaded = load_snapshot(Path(data_root))
    if loaded.error is not None or loaded.snapshot is None:
        return []
    items: list[dict[str, Any]] = []
    for goal in loaded.snapshot.goals.values():
        if not (_matches(goal.title, query) or _matches(goal.description, query)):
            continue
        kind = "计划" if goal.kind == "plan" else "习惯"
        subtitle = goal.target_date or goal.start_date
        items.append(
            {
                "title": goal.title,
                "subtitle": subtitle or "",
                "kind": "goal",
                "route": "/tasks",
                "badge": kind,
            }
        )
        if len(items) >= GROUP_LIMIT:
            break
    return items


def _note_items(data_dir: Path, query: str) -> list[dict[str, Any]]:
    try:
        notes = services.read_notes(data_dir).get("items", [])
    except services.HomeServiceError:
        return []
    items: list[dict[str, Any]] = []
    for note in notes:
        text = note.get("text") or ""
        if not _matches(text, query):
            continue
        items.append({
            "id": note["id"],
            "title": text[:100],
            "subtitle": _friendly_when(note.get("createdAt")),
            "kind": "note",
            "route": "/",
            "params": {"note": note["id"]},
            "badge": "随手记",
        })
        if len(items) >= GROUP_LIMIT:
            break
    return items


def search(
    query: str,
    data_root: Path,
    projects_snapshot: Any = None,
    home_data_dir: Path | None = None,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"query": "", "groups": [], "total": 0}
    needle = query.casefold()[:QUERY_MAX]

    groups = [
        {"key": "projects", "label": "项目", "items": _project_items(projects_snapshot, needle)},
        {"key": "tasks", "label": "待办", "items": _task_items(data_root, needle)},
        {"key": "goals", "label": "长期任务", "items": _goal_items(data_root, needle)},
        {"key": "notes", "label": "随手记", "items": _note_items(Path(home_data_dir) if home_data_dir is not None else Path(data_root).parent, needle)},
    ]
    groups = [group for group in groups if group["items"]]
    return {
        "query": query,
        "groups": groups,
        "total": sum(len(group["items"]) for group in groups),
    }
