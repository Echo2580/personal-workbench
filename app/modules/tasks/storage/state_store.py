"""State snapshot storage: in-memory models, atomic replace, single-process lock.

Implements the snapshot component of 协作/设计/数据与接口契约-v0.1 §2 / §2.1.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import ContextManager
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from app.modules.tasks.domain import Goal, Source, Task


# 版本演进：
#   v1：sources / tasks / confirmedDraftSets
#   v2：新增 goals 分区
#   v3：Task 新增 goalId / occurrenceOf / planRevision（可空字段）
# 读取接受 v1/v2/v3（旧版本视为缺省字段为空，只读路径不改文件）；任何成功
# 写盘都会把版本号升级为 SCHEMA_VERSION（迁移只在写回时发生）。未知版本、
# 损坏 JSON、非法形状仍走原有错误路径。
SCHEMA_VERSION: int = 3
_MAIN_NAME: str = "state.json"
_BAK_NAME: str = "state.json.bak"
_TMP_NAME: str = "state.json.tmp"
_BAK_TMP_NAME: str = "state.json.bak.tmp"

_V1_ROOT_KEYS: frozenset[str] = frozenset(
    {"schemaVersion", "sources", "tasks", "confirmedDraftSets"}
)
_V2_ROOT_KEYS: frozenset[str] = _V1_ROOT_KEYS | {"goals"}
_V3_ROOT_KEYS: frozenset[str] = _V2_ROOT_KEYS
_ROOT_KEYS_BY_VERSION: Mapping[int, frozenset[str]] = {
    1: _V1_ROOT_KEYS,
    2: _V2_ROOT_KEYS,
    3: _V3_ROOT_KEYS,
}
# 可读取（并会在下次写盘时迁移）的版本集合；不在其中的版本仍按原错误上报。
_SUPPORTED_READ_VERSIONS: frozenset[int] = frozenset(_ROOT_KEYS_BY_VERSION)
_SECTIONS_BY_VERSION: Mapping[int, tuple[str, ...]] = {
    1: ("sources", "tasks", "confirmedDraftSets"),
    2: ("sources", "tasks", "goals", "confirmedDraftSets"),
    3: ("sources", "tasks", "goals", "confirmedDraftSets"),
}
_HEX_64 = re.compile(r"[0-9a-fA-F]{64}\Z")
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


def _is_supported_version(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in _SUPPORTED_READ_VERSIONS
    )


# Process-global write lock. Multi-process mutual exclusion is enforced by
# the runtime contract: only one service process may touch the data root.
_write_lock = threading.Lock()


def snapshot_lock() -> ContextManager[None]:
    """公开写锁（T16 项②）：供服务层在同一锁边界内读快照，避免跨模块引用私有名。

    due 查询等只读路径可用它在锁内读完整快照，从而不与会话切换/提交交错。
    """
    return _write_lock


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #


@dataclass
class LoadResult:
    snapshot: "Snapshot | None"
    error: dict[str, Any] | None = None


class _SkipCommit:
    """项③：mutate 返回此哨兵表示「确知无变化」，commit 跳过写盘。

    选择显式 skip 而非内容哈希比较的原因：快照内是 pydantic 模型且可能共享
    引用，全量比较既昂贵又易误判；由调用方在确知无变化的场景（无过期项的
    会话创建、任务不存在的 DELETE、竞态回退）显式声明，零行为风险。
    """

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "SKIP_COMMIT"


SKIP_COMMIT = _SkipCommit()


@dataclass
class CommitResult:
    snapshot: "Snapshot | None"
    error: dict[str, Any] | None = None
    # 项③：本次 commit 因确知无变化而跳过写盘（不产生 tmp/主文件/.bak 轮换）
    skipped: bool = False
    # Optional advisory: the main file was committed successfully but the
    # post-commit backup step failed. This is NOT an error (no new error
    # code, no rollback of the committed main file); the previous .bak is
    # kept and remains a valid snapshot.
    warning: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #


@dataclass
class Snapshot:
    schema_version: int = SCHEMA_VERSION
    sources: dict[str, Source] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    goals: dict[str, Goal] = field(default_factory=dict)
    confirmed_draft_sets: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "Snapshot":
        return cls()

    # --- mutators (return new snapshots to keep the public surface explicit) ---

    def add_source(self, source: Source) -> "Snapshot":
        if source.id in self.sources:
            raise ValueError(f"source {source.id} already present")
        return Snapshot(
            schema_version=self.schema_version,
            sources={**self.sources, source.id: source},
            tasks=self.tasks,
            goals=self.goals,
            confirmed_draft_sets=self.confirmed_draft_sets,
        )

    def add_source_meta(self, meta: Mapping[str, Any]) -> "Snapshot":
        return self.add_source(Source.model_validate(meta))

    def add_task(self, task: Mapping[str, Any] | Task) -> "Snapshot":
        if isinstance(task, Task):
            entity = task
        else:
            entity = Task.model_validate(task)
        if entity.id in self.tasks:
            raise ValueError(f"task {entity.id} already present")
        return Snapshot(
            schema_version=self.schema_version,
            sources=self.sources,
            tasks={**self.tasks, entity.id: entity},
            goals=self.goals,
            confirmed_draft_sets=self.confirmed_draft_sets,
        )

    def add_goal(self, goal: Mapping[str, Any] | Goal) -> "Snapshot":
        """期 2：新增一条长期任务；id 重复视为存储层错误。"""
        if isinstance(goal, Goal):
            entity = goal
        else:
            entity = Goal.model_validate(goal)
        if entity.id in self.goals:
            raise ValueError(f"goal {entity.id} already present")
        return Snapshot(
            schema_version=self.schema_version,
            sources=self.sources,
            tasks=self.tasks,
            goals={**self.goals, entity.id: entity},
            confirmed_draft_sets=self.confirmed_draft_sets,
        )

    def add_confirmation(
        self, record: Mapping[str, Any]
    ) -> "Snapshot":
        """Add a ConfirmationRecord.

        The record's ``draftSetId`` (when present) is used as the dict key in
        ``confirmed_draft_sets``; when absent, a fresh UUID is generated. The
        stored value follows the contract shape ``{requestSha256, response}``
        and never re-injects ``draftSetId``.
        """
        if "requestSha256" not in record:
            raise ValueError("confirmation record missing requestSha256")
        if "response" not in record:
            raise ValueError("confirmation record missing response")
        draft_set_id = record.get("draftSetId")
        if draft_set_id is None:
            draft_set_id = str(uuid.uuid4())
        if not isinstance(draft_set_id, str):
            raise ValueError("confirmation record draftSetId must be a string")
        if not _UUID_PATTERN.fullmatch(draft_set_id):
            raise ValueError(
                "confirmation record draftSetId must be a lowercase standard UUID"
            )
        if draft_set_id in self.confirmed_draft_sets:
            raise ValueError(
                f"confirmation record for {draft_set_id} already present"
            )
        stored_value = {
            "requestSha256": record["requestSha256"],
            "response": deepcopy_payload(record["response"]),
        }
        return Snapshot(
            schema_version=self.schema_version,
            sources=self.sources,
            tasks=self.tasks,
            goals=self.goals,
            confirmed_draft_sets={
                **self.confirmed_draft_sets,
                draft_set_id: stored_value,
            },
        )

    def without(self, draft_set_id: str) -> "Snapshot":
        if draft_set_id not in self.confirmed_draft_sets:
            raise ValueError(f"confirmation record {draft_set_id} not present")
        remaining = {
            key: value
            for key, value in self.confirmed_draft_sets.items()
            if key != draft_set_id
        }
        return Snapshot(
            schema_version=self.schema_version,
            sources=self.sources,
            tasks=self.tasks,
            goals=self.goals,
            confirmed_draft_sets=remaining,
        )

    # --- serialization ---

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "sources": {
                sid: source.model_dump(mode="json", by_alias=True)
                for sid, source in self.sources.items()
            },
            "tasks": {
                tid: task.model_dump(mode="json", by_alias=True)
                for tid, task in self.tasks.items()
            },
            "confirmedDraftSets": {
                cid: deepcopy_payload(record)
                for cid, record in self.confirmed_draft_sets.items()
            },
        }
        # v1 载荷没有 goals 分区：读入的 v1 快照按 v1 形状序列化（写盘前
        # commit 会先把版本号升到当前 schema，再带 goals 输出）。
        if self.schema_version >= 2:
            payload["goals"] = {
                gid: goal.model_dump(mode="json", by_alias=True)
                for gid, goal in self.goals.items()
            }
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Snapshot":
        schema_version = payload.get("schemaVersion", SCHEMA_VERSION)
        snap = cls(schema_version=schema_version)
        for sid, source_payload in payload.get("sources", {}).items():
            source = Source.model_validate(source_payload)
            snap = snap.add_source(source)
        for tid, task_payload in payload.get("tasks", {}).items():
            snap = snap.add_task(task_payload)
        # v1 载荷没有 goals 键：迁移读取时视为空集合（写回时版本号才升级）。
        for gid, goal_payload in payload.get("goals", {}).items():
            snap = snap.add_goal(goal_payload)
        for cid, record in payload.get("confirmedDraftSets", {}).items():
            snap = snap.add_confirmation(
                {
                    "draftSetId": cid,
                    "requestSha256": record["requestSha256"],
                    "response": deepcopy_payload(record.get("response", {})),
                }
            )
        return snap


def deepcopy_payload(value: Any) -> Any:
    """Round-trip a JSON-compatible value to drop any non-serializable state."""
    return json.loads(json.dumps(value, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Public functions
# --------------------------------------------------------------------------- #


def load_snapshot(root: Path) -> LoadResult:
    """Load the current snapshot from `<root>/state.json` if present."""
    main_path = Path(root) / _MAIN_NAME
    if not main_path.exists():
        return LoadResult(snapshot=Snapshot.empty())

    try:
        raw = main_path.read_text(encoding="utf-8")
    except OSError as exc:
        return LoadResult(
            snapshot=None,
            error={
                "code": "storage_read_failed",
                "message": f"unable to read state file: {exc}",
            },
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return LoadResult(
            snapshot=None,
            error={
                "code": "storage_read_failed",
                "message": f"state file is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            },
        )

    if not isinstance(payload, dict):
        return LoadResult(
            snapshot=None,
            error={
                "code": "storage_read_failed",
                "message": "state root must be an object",
            },
        )

    if not _is_supported_version(payload.get("schemaVersion")):
        return LoadResult(
            snapshot=None,
            error={
                "code": "storage_version_unsupported",
                "message": f"unsupported schemaVersion: {payload.get('schemaVersion')!r}",
            },
        )

    errors = snapshot_errors(payload)
    if errors:
        return LoadResult(
            snapshot=None,
            error={
                "code": "storage_read_failed",
                "message": "state file failed validation: " + "; ".join(errors),
            },
        )

    return LoadResult(snapshot=Snapshot.from_payload(payload))


def commit(
    root: Path,
    mutate: Callable[[Snapshot], Snapshot],
) -> CommitResult:
    """Atomically commit a mutation derived from the latest on-disk snapshot."""
    root = Path(root)
    main_path = root / _MAIN_NAME
    bak_path = root / _BAK_NAME
    tmp_path = root / _TMP_NAME
    bak_tmp_path = root / _BAK_TMP_NAME

    with _write_lock:
        loaded = load_snapshot(root)
        if loaded.error is not None:
            return CommitResult(snapshot=None, error=loaded.error)
        baseline = loaded.snapshot

        try:
            mutated = mutate(baseline)
        except Exception as exc:  # noqa: BLE001 - rethrown as storage error
            return CommitResult(
                snapshot=None,
                error={
                    "code": "storage_write_failed",
                    "message": f"mutate raised {type(exc).__name__}: {exc}",
                },
            )

        # 项③：确知无变化 → 跳过写盘（不产生 tmp、主文件与 .bak 轮换）
        if mutated is SKIP_COMMIT:
            return CommitResult(snapshot=baseline, skipped=True)

        if not isinstance(mutated, Snapshot):
            return CommitResult(
                snapshot=None,
                error={
                    "code": "storage_write_failed",
                    "message": "mutate must return a Snapshot instance",
                },
            )

        # 期 2 迁移：读入的旧版本快照在写盘时升级为当前 schema 版本；只读路径
        # 不改文件，因此旧数据只会"读旧写新"，不会静默丢失。
        try:
            write_snapshot = _stamp_current_schema(mutated)
            payload = write_snapshot.to_payload()
        except Exception as exc:  # noqa: BLE001
            return CommitResult(
                snapshot=None,
                error={
                    "code": "storage_write_failed",
                    "message": f"snapshot serialization failed: {exc}",
                },
            )

        errors = snapshot_errors(payload)
        if errors:
            return CommitResult(
                snapshot=None,
                error={
                    "code": "storage_write_failed",
                    "message": "snapshot failed validation: " + "; ".join(errors),
                },
            )

        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            root.mkdir(parents=True, exist_ok=True)

            # 1. Write the new snapshot to a tmp file.
            tmp_path.write_text(serialized, encoding="utf-8")
            # Verify the tmp file is readable and valid JSON before swapping.
            verify = json.loads(tmp_path.read_text(encoding="utf-8"))
            json.dumps(verify, ensure_ascii=False)

            # 2. If a previous main exists, stage a copy of it in bak.tmp.
            #    No replace happens here: the previous .bak must stay
            #    byte-identical until the new main is committed.
            stage_backup = main_path.exists()
            if stage_backup:
                bak_tmp_path.write_bytes(main_path.read_bytes())

            # 3. Atomically swap the new snapshot into place. If this fails,
            #    main and .bak are both byte-unchanged; only tmp leftovers
            #    are cleaned up.
            os.replace(tmp_path, main_path)
        except (OSError, json.JSONDecodeError) as exc:
            # The main file was NOT replaced: clean up tmp leftovers only.
            # main and .bak are both untouched.
            for leftover in (tmp_path, bak_tmp_path):
                try:
                    if leftover.exists():
                        leftover.unlink()
                except OSError:
                    pass
            return CommitResult(
                snapshot=None,
                error={
                    "code": "storage_write_failed",
                    "message": f"atomic replace failed: {exc}",
                },
            )

        # 4. Main file is committed. The previous main becomes the backup:
        #    a failure here does not roll back the committed snapshot, so the
        #    commit is still successful; the older .bak is kept as a valid
        #    snapshot of some earlier generation.
        warning: dict[str, Any] | None = None
        if stage_backup:
            try:
                os.replace(bak_tmp_path, bak_path)
            except OSError as exc:
                warning = {
                    "code": "backup_not_refreshed",
                    "message": (
                        "main file committed, but refreshing state.json.bak "
                        f"failed: {exc}"
                    ),
                }
                try:
                    if bak_tmp_path.exists():
                        bak_tmp_path.unlink()
                except OSError:
                    pass

    return CommitResult(snapshot=write_snapshot, warning=warning)


def _stamp_current_schema(snapshot: Snapshot) -> Snapshot:
    """返回写盘用的快照：版本号统一升级为 ``SCHEMA_VERSION``。

    迁移语义：v1/v2/v3 快照都可以正常读取（``Snapshot.schema_version`` 保持
    磁盘上的原版本），只有 commit 真正写盘时才升到当前版本。旧版本缺省的
    字段（v1 的 goals、v2 的 Task.goalId 等）由实体模型的可空默认值补齐，
    分区数据原样搬运，不做任何数据清洗或丢弃。未知版本拒绝写入。
    """
    if snapshot.schema_version == SCHEMA_VERSION:
        return snapshot
    if snapshot.schema_version not in _SUPPORTED_READ_VERSIONS:
        raise ValueError(
            f"mutate returned unsupported schemaVersion: {snapshot.schema_version!r}"
        )
    return Snapshot(
        schema_version=SCHEMA_VERSION,
        sources=snapshot.sources,
        tasks=snapshot.tasks,
        goals=snapshot.goals,
        confirmed_draft_sets=snapshot.confirmed_draft_sets,
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def snapshot_errors(payload: Mapping[str, Any]) -> list[str]:
    """Return a list of human-readable errors. Empty list means valid."""
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["snapshot root must be a JSON object"]

    schema_version = payload.get("schemaVersion")
    if not _is_supported_version(schema_version):
        errors.append(
            "schemaVersion must be one of "
            f"{sorted(_SUPPORTED_READ_VERSIONS)}, got {schema_version!r}"
        )
        # Without a readable schema we cannot meaningfully inspect the rest.
        return errors

    allowed_root_keys = _ROOT_KEYS_BY_VERSION[schema_version]
    unknown_root_keys = sorted(set(payload) - allowed_root_keys)
    if unknown_root_keys:
        errors.append(
            "snapshot root must have exactly "
            f"{sorted(allowed_root_keys)} keys; got extra {unknown_root_keys!r}"
        )

    for section in _SECTIONS_BY_VERSION[schema_version]:
        section_value = payload.get(section)
        if not isinstance(section_value, Mapping):
            errors.append(f"{section} must be a JSON object")

    sources = payload.get("sources", {})
    if isinstance(sources, Mapping):
        for key, value in sources.items():
            if not isinstance(key, str):
                errors.append("source key must be a string")
                continue
            if not isinstance(value, Mapping):
                errors.append(f"source {key} must be an object")
                continue
            try:
                source = Source.model_validate(value)
            except ValidationError as exc:
                errors.append(f"source {key}: {format_pydantic_error(exc)}")
                continue
            if source.id != key:
                errors.append(
                    f"source key {key!r} does not match entity id {source.id!r}"
                )

    tasks = payload.get("tasks", {})
    if isinstance(tasks, Mapping):
        for key, value in tasks.items():
            if not isinstance(key, str):
                errors.append("task key must be a string")
                continue
            if not isinstance(value, Mapping):
                errors.append(f"task {key} must be an object")
                continue
            try:
                task = Task.model_validate(value)
            except ValidationError as exc:
                errors.append(f"task {key}: {format_pydantic_error(exc)}")
                continue
            if task.id != key:
                errors.append(
                    f"task key {key!r} does not match entity id {task.id!r}"
                )

    goals = payload.get("goals", {})
    if isinstance(goals, Mapping):
        for key, value in goals.items():
            if not isinstance(key, str):
                errors.append("goal key must be a string")
                continue
            if not isinstance(value, Mapping):
                errors.append(f"goal {key} must be an object")
                continue
            try:
                goal = Goal.model_validate(value)
            except ValidationError as exc:
                errors.append(f"goal {key}: {format_pydantic_error(exc)}")
                continue
            if goal.id != key:
                errors.append(
                    f"goal key {key!r} does not match entity id {goal.id!r}"
                )

    confirmations = payload.get("confirmedDraftSets", {})
    if isinstance(confirmations, Mapping):
        for key, value in confirmations.items():
            if not isinstance(key, str) or not _UUID_PATTERN.fullmatch(key):
                errors.append(
                    f"confirmation key {key!r} must be a lowercase standard UUID"
                )
            if not isinstance(value, Mapping):
                errors.append(f"confirmation {key} must be an object")
                continue
            unexpected_value_keys = sorted(set(value) - {"requestSha256", "response"})
            if unexpected_value_keys:
                errors.append(
                    f"confirmation {key} value must have exactly "
                    f"{{'requestSha256', 'response'}} keys; got extra "
                    f"{unexpected_value_keys!r}"
                )
            sha = value.get("requestSha256")
            if not isinstance(sha, str) or not _HEX_64.fullmatch(sha):
                errors.append(
                    f"confirmation {key} requestSha256 must be a 64-character hex string"
                )
            if not isinstance(value.get("response"), Mapping):
                errors.append(f"confirmation {key} response must be an object")

    return errors


def format_pydantic_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)
