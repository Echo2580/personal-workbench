"""Reminder runtime: sessions, expiry scan, due filtering, §4.3 acknowledgment.

Sessions live only in process memory (app.state), never persisted — a restart
therefore loses every session ID, which is exactly the 404 semantics the
contract requires.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.tasks.api import ApiError
from app.modules.tasks.domain import Task
from app.modules.tasks.storage import (
    SKIP_COMMIT,
    Snapshot,
    commit,
    load_snapshot,
    snapshot_lock,
)


INTERVAL_SECONDS = 5

_STORAGE_ERROR_CODES = (
    "storage_read_failed",
    "storage_write_failed",
    "storage_version_unsupported",
)


def parse_moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


# --------------------------------------------------------------------------- #
# session registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReminderSession:
    session_id: str
    started_at: str
    interval_seconds: int = INTERVAL_SECONDS

    def to_payload(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "startedAt": self.started_at,
            "intervalSeconds": self.interval_seconds,
        }


@dataclass
class SessionRegistry:
    """当前会话 + 本进程已知的已取代会话 ID（供 409 判定）。"""

    current: ReminderSession | None = None
    superseded: set[str] = field(default_factory=set)


def remember_session(registry: SessionRegistry, session: ReminderSession) -> None:
    """Make ``session`` current; the previous one becomes superseded."""
    if registry.current is not None:
        registry.superseded.add(registry.current.session_id)
    registry.current = session


# --------------------------------------------------------------------------- #
# outcomes
# --------------------------------------------------------------------------- #


@dataclass
class OpenSessionOutcome:
    status_code: int
    body: dict[str, Any] | None = None
    error: ApiError | None = None
    expired: int = 0


@dataclass
class DueOutcome:
    status_code: int
    body: dict[str, Any] | None = None
    error: ApiError | None = None


@dataclass
class AckOutcome:
    status_code: int
    step: int
    body: dict[str, Any] | None = None
    error: ApiError | None = None
    # 仅第 6 步非空：需要原子写入的替换任务（第 3 步回放时为 None，只读）
    task: Task | None = None


def _storage_error(error: dict[str, Any]) -> ApiError:
    code = str(error.get("code", "storage_read_failed"))
    if code not in _STORAGE_ERROR_CODES:
        code = "storage_read_failed"
    return ApiError(500, code, str(error.get("message", "存储操作失败。")))


def _replace_task(snapshot: Snapshot, task: Task) -> Snapshot:
    return Snapshot(
        schema_version=snapshot.schema_version,
        sources=snapshot.sources,
        tasks={**snapshot.tasks, task.id: task},
        goals=snapshot.goals,
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )


# --------------------------------------------------------------------------- #
# expiry scan
# --------------------------------------------------------------------------- #


def expire_stale_reminders(
    snapshot: Snapshot, started_at: str
) -> tuple[Snapshot, int, list[str]]:
    """Set state=expired on open tasks whose scheduled reminder predates the
    session start. All other fields (scheduledAt/revision/...) stay untouched.
    """
    threshold = parse_moment(started_at)
    changed: dict[str, Task] = {}

    for task_id, task in snapshot.tasks.items():
        reminder = task.reminder
        if reminder.state != "scheduled" or reminder.scheduled_at is None:
            continue
        if task.status != "open":
            continue
        if parse_moment(reminder.scheduled_at) >= threshold:
            continue
        payload = task.model_dump(mode="json", by_alias=True)
        payload["reminder"] = {**payload["reminder"], "state": "expired"}
        changed[task_id] = Task.model_validate(payload)

    if not changed:
        return snapshot, 0, []
    return _replace_many(snapshot, changed), len(changed), sorted(changed)


def _replace_many(snapshot: Snapshot, replacements: dict[str, Task]) -> Snapshot:
    return Snapshot(
        schema_version=snapshot.schema_version,
        sources=snapshot.sources,
        tasks={**snapshot.tasks, **replacements},
        goals=snapshot.goals,
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )


# --------------------------------------------------------------------------- #
# POST /reminder-sessions
# --------------------------------------------------------------------------- #


def open_session(
    root: Path, registry: SessionRegistry, now: datetime
) -> OpenSessionOutcome:
    """Expire stale reminders inside the write lock, then publish the session."""
    session = ReminderSession(
        session_id=str(uuid.uuid4()), started_at=now.isoformat()
    )
    expired_holder: dict[str, int] = {"count": 0}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        updated, count, _ = expire_stale_reminders(snapshot, session.started_at)
        expired_holder["count"] = count
        # 项③：无过期项 → 确知无变化，跳过写盘（避免每次开页的无谓写盘与
        # .bak 轮换）；有过期项照常提交。
        if count == 0:
            return SKIP_COMMIT  # type: ignore[return-value]
        return updated

    result = commit(root, _mutate)
    if result.error is not None:
        # 提交失败：保留原会话（不替换）
        return OpenSessionOutcome(500, error=_storage_error(result.error))

    # 提交成功后才替换当前会话
    remember_session(registry, session)
    return OpenSessionOutcome(
        200, body=session.to_payload(), expired=expired_holder["count"]
    )


# --------------------------------------------------------------------------- #
# GET /reminder-sessions/{id}/due
# --------------------------------------------------------------------------- #


def due_reminders(
    root: Path,
    registry: SessionRegistry,
    session_id: str,
    now: datetime,
) -> DueOutcome:
    """Return due items for the current session, read inside the shared lock."""
    # 与会话创建/确认共用 storage 公开写锁（契约 §2.1）
    with snapshot_lock():
        session = registry.current
        if session is None or session.session_id != session_id:
            if session_id in registry.superseded:
                return DueOutcome(
                    409,
                    error=ApiError(
                        409,
                        "reminder_session_superseded",
                        "该提醒会话已被新会话取代。",
                    ),
                )
            return DueOutcome(
                404,
                error=ApiError(
                    404, "reminder_session_not_found", "提醒会话不存在。"
                ),
            )

        loaded = load_snapshot(root)
        if loaded.error is not None:
            return DueOutcome(500, error=_storage_error(loaded.error))
        assert loaded.snapshot is not None

        started = parse_moment(session.started_at)
        reminders: list[dict[str, Any]] = []
        for task in loaded.snapshot.tasks.values():
            reminder = task.reminder
            if reminder.state != "scheduled" or reminder.scheduled_at is None:
                continue
            if task.status != "open":
                continue
            moment = parse_moment(reminder.scheduled_at)
            if not (started <= moment <= now):
                continue
            reminders.append(
                {
                    "taskId": task.id,
                    "title": task.title,
                    "sourceId": task.source_id,
                    "scheduledAt": reminder.scheduled_at,
                    "state": reminder.state,
                    "reminderVersion": reminder.revision,
                }
            )

        # 稳定排序：scheduledAt 升序，同一时刻按 taskId 升序
        reminders.sort(key=lambda item: item["taskId"])
        reminders.sort(key=lambda item: item["scheduledAt"])

    return DueOutcome(200, body={"checkedAt": now.isoformat(), "reminders": reminders})


# --------------------------------------------------------------------------- #
# §4.3 acknowledgment: fixed six-step order, each step short-circuits
# --------------------------------------------------------------------------- #


def _conditions_valid(task: Task) -> bool:
    try:
        task.reminder.scheduled_against(
            task.start_time, task.due_time, task.applicability
        )
    except ValueError:
        return False
    return True


def acknowledge(
    snapshot: Snapshot,
    task_id: str,
    session_id: str,
    version: str,
    now: datetime,
    registry: SessionRegistry,
) -> AckOutcome:
    """Steps 1–6 of 契约 §4.3. Step 6 only *builds* the write; the caller
    commits it. Steps 1–5 never write anything.
    """
    # 1. 最新快照中查找任务
    task = snapshot.tasks.get(task_id)
    if task is None:
        return AckOutcome(
            404,
            1,
            error=ApiError(404, "task_not_found", "任务不存在。"),
        )

    reminder = task.reminder

    # 2. 版本必须一致（即使当前已 acknowledged 也不冒名回放）
    if reminder.revision != version:
        return AckOutcome(
            409,
            2,
            error=ApiError(
                409,
                "reminder_version_conflict",
                "提醒版本已变化，请以当前版本重新确认。",
            ),
        )

    # 3. 同版本且已确认 → 只读回放（优先于会话查验）
    if reminder.state == "acknowledged":
        return AckOutcome(
            200,
            3,
            body={
                "taskId": task.id,
                "reminderVersion": reminder.revision,
                "state": "acknowledged",
                "acknowledgedAt": reminder.acknowledged_at,
            },
        )

    # 4. 非可确认状态；scheduled 但任务/条件无效同样拒绝
    if reminder.state in ("expired", "cancelled", "blocked", "not_set"):
        return AckOutcome(
            409,
            4,
            error=ApiError(
                409,
                "reminder_not_acknowledgeable",
                "当前提醒状态不可确认。",
            ),
        )
    if task.status != "open" or not _conditions_valid(task):
        return AckOutcome(
            409,
            4,
            error=ApiError(
                409,
                "reminder_not_acknowledgeable",
                "当前提醒状态不可确认。",
            ),
        )

    # 5. 会话有效性 + 到期区间
    current = registry.current
    if current is None or current.session_id != session_id:
        if session_id in registry.superseded:
            return AckOutcome(
                409,
                5,
                error=ApiError(
                    409,
                    "reminder_session_superseded",
                    "该提醒会话已被新会话取代。",
                ),
            )
        return AckOutcome(
            404,
            5,
            error=ApiError(
                404, "reminder_session_not_found", "提醒会话不存在。"
            ),
        )
    started = parse_moment(current.started_at)
    scheduled = parse_moment(reminder.scheduled_at) if reminder.scheduled_at else None
    if scheduled is None or not (started <= scheduled <= now):
        return AckOutcome(
            409,
            5,
            error=ApiError(
                409,
                "reminder_not_acknowledgeable",
                "提醒尚未到期或不在本会话区间内。",
            ),
        )

    # 6. 生成待写入的任务（revision 不变）
    acknowledged_at = now.isoformat()
    payload = task.model_dump(mode="json", by_alias=True)
    payload["reminder"] = {
        **payload["reminder"],
        "state": "acknowledged",
        "acknowledgedAt": acknowledged_at,
    }
    updated = Task.model_validate(payload)
    return AckOutcome(
        200,
        6,
        body={
            "taskId": updated.id,
            "reminderVersion": updated.reminder.revision,
            "state": "acknowledged",
            "acknowledgedAt": acknowledged_at,
        },
        task=updated,
    )


def acknowledge_reminder(
    root: Path,
    registry: SessionRegistry,
    task_id: str,
    session_id: str,
    version: str,
    now: datetime,
) -> AckOutcome:
    """Run §4.3: read-only steps first, then commit step 6 inside the lock."""
    loaded = load_snapshot(root)
    if loaded.error is not None:
        return AckOutcome(500, 1, error=_storage_error(loaded.error))
    assert loaded.snapshot is not None

    probe = acknowledge(loaded.snapshot, task_id, session_id, version, now, registry)
    if probe.task is None:
        # 步骤 1–5 的分支完全不写盘
        return probe

    holder: dict[str, AckOutcome] = {}

    def _mutate(snapshot: Snapshot) -> Snapshot:
        outcome = acknowledge(
            snapshot, task_id, session_id, version, now, registry
        )
        holder["outcome"] = outcome
        if outcome.task is None:
            # 并发导致状态变化：不写入，按最新结果回答
            return snapshot
        return _replace_task(snapshot, outcome.task)

    result = commit(root, _mutate)
    if result.error is not None:
        return AckOutcome(500, 6, error=_storage_error(result.error))
    return holder["outcome"]
