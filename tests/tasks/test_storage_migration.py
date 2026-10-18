"""存储迁移测试：schema v1 / v2 → 当前版本（v3）的安全读取与写回升级。

期 3.1 起 SCHEMA_VERSION = 3（Task 增加 goalId/occurrenceOf/planRevision）。

覆盖：
- v1（无 goals）→ 读为 goals={} → 下次 commit 写回 v3；
- v2（有 goals、Task 无新字段）→ Task 新字段补 null → 下次 commit 写回 v3；
- v3 正常读写；
- 迁移字段逐键保留、无数据丢失、``.bak`` 为升级前原文；
- 重复读幂等（只读路径不改文件）；
- 损坏 JSON / 未知版本 / 未知根键仍走原有错误路径。

所有数据均为存储组件测试的构造样本，不代表真实业务数据。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.tasks.storage.state_store import (
    SCHEMA_VERSION,
    SKIP_COMMIT,
    commit,
    load_snapshot,
    snapshot_errors,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "33333333-3333-4333-8333-000000000001"
DRAFT_ID = "66666666-6666-4666-8666-666666666666"
VERSION = "55555555-5555-4555-8555-555555555555"
SET_ID = "44444444-4444-4444-8444-444444444444"
GOAL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_GOAL_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
STAMP = "2026-10-18T12:00:00+08:00"

# 期 3 给 Task 增加的三个可选字段（v2 及更早的落盘文件没有这些键）
_TASK_OPTIONAL_KEYS = ("goalId", "occurrenceOf", "planRevision")


def _source_payload() -> dict[str, Any]:
    return {
        "id": SOURCE_ID,
        "kind": "text",
        "originalText": "请交报告",
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": "a" * 64,
    }


def _task_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": TASK_ID,
        "draftId": DRAFT_ID,
        "sourceId": SOURCE_ID,
        "title": "交报告",
        "startTime": None,
        "dueTime": None,
        "requirements": ["打印"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告",
        "reviewIssues": [],
        "status": "open",
        "reminder": {
            "mode": "none",
            "requestedAt": None,
            "scheduledAt": None,
            "relativeTo": None,
            "offsetMinutes": None,
            "state": "not_set",
            "acknowledgedAt": None,
            "revision": VERSION,
        },
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }
    payload.update(overrides)
    return payload


def _goal_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": GOAL_ID,
        "kind": "plan",
        "title": "考研复习",
        "description": None,
        "startDate": "2026-10-20",
        "targetDate": "2027-06-30",
        "dailyCapacity": 3,
        "constraints": None,
        "recurrence": None,
        "status": "active",
        "planRevision": 0,
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }
    payload.update(overrides)
    return payload


def _confirmation_value() -> dict[str, Any]:
    return {
        "requestSha256": "f" * 64,
        "response": {"sourceId": SOURCE_ID, "taskIds": [TASK_ID], "savedAt": STAMP},
    }


def _v1_payload() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "sources": {SOURCE_ID: _source_payload()},
        "tasks": {TASK_ID: _task_payload()},
        "confirmedDraftSets": {SET_ID: _confirmation_value()},
    }


def _v2_payload(goals: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _v1_payload()
    payload["schemaVersion"] = 2
    payload["goals"] = {} if goals is None else goals
    return payload


def _v3_payload(goals: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _v2_payload({GOAL_ID: _goal_payload()} if goals is None else goals)
    payload["schemaVersion"] = 3
    return payload


def _write_payload(root: Path, payload: dict[str, Any]) -> None:
    (root / "state.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _read_payload(root: Path) -> dict[str, Any]:
    return json.loads((root / "state.json").read_text(encoding="utf-8"))


def _read_bytes(root: Path) -> bytes:
    return (root / "state.json").read_bytes()


def _bak_bytes(root: Path) -> bytes | None:
    path = root / "state.json.bak"
    return path.read_bytes() if path.exists() else None


def _v1_data(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in ("schemaVersion", "goals")
    }


def _canonical(payload: dict[str, Any]) -> dict[str, Any]:
    """去掉 Task 新增可选字段的 null 值，便于与旧版本夹具逐键比较。"""
    clone = json.loads(json.dumps(payload, ensure_ascii=False))
    for task in clone.get("tasks", {}).values():
        for key in _TASK_OPTIONAL_KEYS:
            if task.get(key) is None:
                task.pop(key, None)
    return clone


def _assert_original_task_preserved(
    persisted: dict[str, Any], original: dict[str, Any]
) -> None:
    """v1/v2 任务原有字段必须逐键保留；新增字段只允许是 null。"""
    assert {key: persisted[key] for key in original} == original
    for key in _TASK_OPTIONAL_KEYS:
        assert persisted.get(key) is None


# --------------------------------------------------------------------------- #
# v1 / v2 / v3 读取兼容
# --------------------------------------------------------------------------- #


def test_empty_root_starts_at_current_schema(tmp_path: Path):
    result = load_snapshot(tmp_path)

    assert result.error is None
    assert result.snapshot is not None
    assert result.snapshot.schema_version == SCHEMA_VERSION == 3
    assert result.snapshot.goals == {}
    # 读取不得凭空创建 state.json
    assert not (tmp_path / "state.json").exists()


def test_v1_without_goals_loads_as_empty_goals(tmp_path: Path):
    original = _v1_payload()
    _write_payload(tmp_path, original)
    before = _read_bytes(tmp_path)

    result = load_snapshot(tmp_path)

    assert result.error is None
    assert result.snapshot is not None
    # 读到的仍是 v1（写回时才升级）
    assert result.snapshot.schema_version == 1
    assert result.snapshot.goals == {}
    assert set(result.snapshot.sources) == {SOURCE_ID}
    assert set(result.snapshot.tasks) == {TASK_ID}
    assert set(result.snapshot.confirmed_draft_sets) == {SET_ID}
    # 只读路径不改文件
    assert _read_bytes(tmp_path) == before


def test_v2_loads_with_task_goal_fields_null(tmp_path: Path):
    payload = _v2_payload({GOAL_ID: _goal_payload()})
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is None, loaded.error
    assert loaded.snapshot.schema_version == 2
    assert set(loaded.snapshot.goals) == {GOAL_ID}
    task = loaded.snapshot.tasks[TASK_ID]
    assert task.goal_id is None
    assert task.occurrence_of is None
    assert task.plan_revision is None
    assert _read_bytes(tmp_path) == before


def test_v3_loads_task_goal_fields(tmp_path: Path):
    task = _task_payload(
        goalId=GOAL_ID, occurrenceOf=GOAL_ID, planRevision=2
    )
    payload = _v3_payload()
    payload["tasks"][TASK_ID] = task
    _write_payload(tmp_path, payload)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is None, loaded.error
    assert loaded.snapshot.schema_version == 3
    loaded_task = loaded.snapshot.tasks[TASK_ID]
    assert loaded_task.goal_id == GOAL_ID
    assert loaded_task.occurrence_of == GOAL_ID
    assert loaded_task.plan_revision == 2


# --------------------------------------------------------------------------- #
# v1 → v3：读旧写新
# --------------------------------------------------------------------------- #


def test_v1_read_repeatedly_is_idempotent(tmp_path: Path):
    first = _v1_payload()
    _write_payload(tmp_path, first)
    before = _read_bytes(tmp_path)

    for _ in range(3):
        loaded = load_snapshot(tmp_path)
        assert loaded.error is None, loaded.error
        assert _canonical(loaded.snapshot.to_payload()) == _canonical(first)

    assert _read_bytes(tmp_path) == before


def test_v1_upgrades_to_current_schema_on_next_commit(tmp_path: Path):
    original = _v1_payload()
    _write_payload(tmp_path, original)
    before = _read_bytes(tmp_path)
    assert _bak_bytes(tmp_path) is None

    # 先按 v1 读取（goals 视为空集）
    loaded = load_snapshot(tmp_path)
    assert loaded.error is None
    assert loaded.snapshot.schema_version == 1
    assert loaded.snapshot.goals == {}

    goal = _goal_payload()
    result = commit(tmp_path, lambda snap: snap.add_goal(goal))

    assert result.error is None, result.error
    assert result.snapshot is not None
    assert result.snapshot.schema_version == SCHEMA_VERSION == 3
    assert set(result.snapshot.goals) == {GOAL_ID}

    on_disk = _read_payload(tmp_path)
    assert on_disk["schemaVersion"] == 3
    assert set(on_disk) == {
        "schemaVersion",
        "sources",
        "tasks",
        "goals",
        "confirmedDraftSets",
    }
    # 迁移不得静默丢数据：v1 的三个数据分区逐键等价
    assert _v1_data(_canonical(on_disk)) == _v1_data(_canonical(original))
    _assert_original_task_preserved(on_disk["tasks"][TASK_ID], _task_payload())
    assert on_disk["goals"] == {GOAL_ID: goal}
    # .bak 为升级前原文（v1 字节）
    assert _bak_bytes(tmp_path) == before

    # 升级后按 v3 重新读取
    reread = load_snapshot(tmp_path)
    assert reread.error is None
    assert reread.snapshot is not None
    assert reread.snapshot.schema_version == 3
    assert reread.snapshot.goals[GOAL_ID].title == "考研复习"
    assert set(reread.snapshot.tasks) == {TASK_ID}


def test_v1_noop_commit_also_upgrades(tmp_path: Path):
    """即使 mutate 原样返回快照，只要写盘就升级为当前版本。"""
    original = _v1_payload()
    _write_payload(tmp_path, original)
    before = _read_bytes(tmp_path)

    result = commit(tmp_path, lambda snap: snap)

    assert result.error is None
    assert result.snapshot is not None
    assert result.snapshot.schema_version == SCHEMA_VERSION
    on_disk = _read_payload(tmp_path)
    assert on_disk["schemaVersion"] == 3
    assert on_disk["goals"] == {}
    assert _v1_data(_canonical(on_disk)) == _v1_data(_canonical(original))
    # .bak 为升级前原文
    assert _bak_bytes(tmp_path) == before


def test_v1_skip_commit_does_not_rewrite(tmp_path: Path):
    """SKIP_COMMIT 表示确知无变化：不写盘，也就不会升级版本号。"""
    original = _v1_payload()
    _write_payload(tmp_path, original)
    before = _read_bytes(tmp_path)

    result = commit(tmp_path, lambda snap: SKIP_COMMIT)  # type: ignore[arg-type]

    assert result.error is None
    assert result.skipped is True
    assert result.snapshot is not None
    assert result.snapshot.schema_version == 1
    assert _read_bytes(tmp_path) == before
    assert _read_payload(tmp_path)["schemaVersion"] == 1


# --------------------------------------------------------------------------- #
# v2 → v3：Task 新字段补 null，goals 原样保留
# --------------------------------------------------------------------------- #


def test_v2_upgrades_to_current_schema_on_commit(tmp_path: Path):
    original = _v2_payload({GOAL_ID: _goal_payload()})
    _write_payload(tmp_path, original)
    before = _read_bytes(tmp_path)
    assert _bak_bytes(tmp_path) is None

    result = commit(tmp_path, lambda snap: snap)

    assert result.error is None, result.error
    assert result.snapshot is not None
    assert result.snapshot.schema_version == SCHEMA_VERSION == 3

    on_disk = _read_payload(tmp_path)
    assert on_disk["schemaVersion"] == 3
    assert on_disk["goals"] == {GOAL_ID: _goal_payload()}
    assert on_disk["sources"] == original["sources"]
    assert on_disk["confirmedDraftSets"] == original["confirmedDraftSets"]
    # Task 原有字段逐键保留；新增 goalId/occurrenceOf/planRevision 为 null
    _assert_original_task_preserved(on_disk["tasks"][TASK_ID], _task_payload())
    # .bak 为升级前原文（v2 字节）
    assert _bak_bytes(tmp_path) == before
    # 重新读取为 v3
    reread = load_snapshot(tmp_path)
    assert reread.error is None
    assert reread.snapshot.schema_version == 3
    assert reread.snapshot.tasks[TASK_ID].goal_id is None


def test_v2_commit_appends_without_losing_existing(tmp_path: Path):
    payload = _v2_payload({GOAL_ID: _goal_payload()})
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    second = _goal_payload(
        id=OTHER_GOAL_ID,
        kind="habit",
        title="晨跑",
        targetDate=None,
        dailyCapacity=None,
        recurrence={
            "freq": "daily",
            "weekdays": [],
            "time": "07:00",
            "durationMinutes": 30,
        },
    )
    result = commit(tmp_path, lambda snap: snap.add_goal(second))

    assert result.error is None, result.error
    on_disk = _read_payload(tmp_path)
    assert on_disk["schemaVersion"] == 3
    assert set(on_disk["goals"]) == {GOAL_ID, OTHER_GOAL_ID}
    assert on_disk["goals"][GOAL_ID] == _goal_payload()
    assert _bak_bytes(tmp_path) == before


# --------------------------------------------------------------------------- #
# v3 正常读写
# --------------------------------------------------------------------------- #


def test_v3_round_trips_through_disk(tmp_path: Path):
    payload = _v3_payload()
    payload["tasks"][TASK_ID] = _task_payload(
        goalId=GOAL_ID, occurrenceOf=GOAL_ID, planRevision=1
    )
    _write_payload(tmp_path, payload)

    loaded = load_snapshot(tmp_path)
    assert loaded.error is None, loaded.error
    assert loaded.snapshot.schema_version == 3
    assert set(loaded.snapshot.goals) == {GOAL_ID}
    assert loaded.snapshot.tasks[TASK_ID].goal_id == GOAL_ID
    assert loaded.snapshot.tasks[TASK_ID].plan_revision == 1
    assert loaded.snapshot.to_payload() == payload
    assert snapshot_errors(payload) == []


def test_v3_missing_goals_section_is_rejected(tmp_path: Path):
    payload = _v3_payload()
    del payload["goals"]
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "goals" in loaded.error["message"]
    assert _read_bytes(tmp_path) == before


# --------------------------------------------------------------------------- #
# 损坏 / 未知版本 / 未知根键：仍走原有错误路径
# --------------------------------------------------------------------------- #


def test_corrupt_json_still_returns_storage_read_failed(tmp_path: Path):
    corrupt = '{"schemaVersion":3,"sources":{'
    (tmp_path / "state.json").write_text(corrupt, encoding="utf-8")
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)
    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"

    result = commit(tmp_path, lambda snap: snap)
    assert result.error is not None
    assert result.error["code"] == "storage_read_failed"
    assert _read_bytes(tmp_path) == before


@pytest.mark.parametrize("version", [0, 4, 99, 2.0, "2", None, True])
def test_unknown_schema_version_still_unsupported(tmp_path: Path, version: Any):
    payload = _v2_payload()
    payload["schemaVersion"] = version
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)
    assert loaded.error is not None
    assert loaded.error["code"] == "storage_version_unsupported"
    assert _read_bytes(tmp_path) == before

    result = commit(tmp_path, lambda snap: snap)
    assert result.error is not None
    assert result.error["code"] == "storage_version_unsupported"
    assert _read_bytes(tmp_path) == before


def test_v1_payload_with_goals_key_is_rejected_not_dropped(tmp_path: Path):
    payload = _v1_payload()
    payload["goals"] = {}
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "goals" in loaded.error["message"]
    assert _read_bytes(tmp_path) == before


def test_v1_unknown_root_key_is_rejected_not_dropped(tmp_path: Path):
    payload = _v1_payload()
    payload["futureField"] = {"keep": "me"}
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "futureField" in loaded.error["message"]
    assert _read_bytes(tmp_path) == before


def test_v2_missing_goals_section_is_rejected(tmp_path: Path):
    payload = _v2_payload()
    del payload["goals"]
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "goals" in loaded.error["message"]
    assert _read_bytes(tmp_path) == before


def test_v2_goal_key_id_mismatch_is_rejected(tmp_path: Path):
    payload = _v2_payload({OTHER_GOAL_ID: _goal_payload()})
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "does not match entity id" in loaded.error["message"]
    assert _read_bytes(tmp_path) == before


def test_invalid_goal_entity_on_disk_is_rejected(tmp_path: Path):
    # plan 缺少 targetDate：互斥校验应阻止该实体被读入
    payload = _v2_payload({GOAL_ID: _goal_payload(targetDate=None)})
    _write_payload(tmp_path, payload)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "goal " in loaded.error["message"]


def test_invalid_goal_write_fails_atomically(tmp_path: Path):
    seed = commit(tmp_path, lambda snap: snap)
    assert seed.error is None, seed.error
    before = _read_bytes(tmp_path)

    result = commit(
        tmp_path, lambda snap: snap.add_goal(_goal_payload(dailyCapacity=None))
    )

    assert result.error is not None
    assert result.error["code"] == "storage_write_failed"
    assert _read_bytes(tmp_path) == before
    reloaded = load_snapshot(tmp_path)
    assert reloaded.error is None
    assert reloaded.snapshot.goals == {}


def test_v3_invalid_task_goal_id_is_rejected(tmp_path: Path):
    payload = _v3_payload()
    payload["tasks"][TASK_ID] = _task_payload(goalId="not-a-uuid")
    _write_payload(tmp_path, payload)
    before = _read_bytes(tmp_path)

    loaded = load_snapshot(tmp_path)

    assert loaded.error is not None
    assert loaded.error["code"] == "storage_read_failed"
    assert "goalId" in loaded.error["message"]
    assert _read_bytes(tmp_path) == before


def test_snapshot_errors_accepts_all_supported_versions():
    assert snapshot_errors(_v1_payload()) == []
    assert snapshot_errors(_v2_payload()) == []
    assert snapshot_errors(_v3_payload()) == []
    assert snapshot_errors(_v2_payload({GOAL_ID: _goal_payload()})) == []

    broken = _v3_payload()
    broken["unknown"] = 1
    assert snapshot_errors(broken)


# --------------------------------------------------------------------------- #
# 端到端：旧版本落盘数据经 HTTP 读后，首次写操作完成 v3 升级
# --------------------------------------------------------------------------- #


def test_v1_state_upgrades_through_first_api_write(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.modules.tasks.app_factory import create_tasks_app

    root = tmp_path / "data"
    root.mkdir()
    original = _v1_payload()
    (root / "state.json").write_text(
        json.dumps(original, ensure_ascii=False), encoding="utf-8"
    )
    original_bytes = (root / "state.json").read_bytes()

    client = TestClient(create_tasks_app(root))

    # 读路径：v1 数据正常返回；goals 视为空集
    tasks = client.get("/api/v1/tasks", params={"status": "all"})
    assert tasks.status_code == 200, tasks.text
    assert [task["id"] for task in tasks.json()["tasks"]] == [TASK_ID]
    goals = client.get("/api/v1/goals")
    assert goals.status_code == 200
    assert goals.json() == {"goals": []}
    # 只读访问不得改写版本号
    assert _read_payload(root)["schemaVersion"] == 1

    # 首次写操作：v1 → v3，旧分区原样保留，.bak 为升级前原文
    created = client.post(
        "/api/v1/goals",
        json={
            "kind": "plan",
            "title": "考研复习",
            "startDate": "2026-10-20",
            "targetDate": "2027-06-30",
            "dailyCapacity": 3,
        },
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["goal"]["id"]

    on_disk = _read_payload(root)
    assert on_disk["schemaVersion"] == SCHEMA_VERSION == 3
    assert set(on_disk["goals"]) == {goal_id}
    _assert_original_task_preserved(on_disk["tasks"][TASK_ID], _task_payload())
    assert on_disk["sources"][SOURCE_ID] == _source_payload()
    assert on_disk["confirmedDraftSets"][SET_ID] == _confirmation_value()
    assert (root / "state.json.bak").read_bytes() == original_bytes


def test_v2_state_upgrades_through_first_api_write(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.modules.tasks.app_factory import create_tasks_app

    root = tmp_path / "data"
    root.mkdir()
    original = _v2_payload({GOAL_ID: _goal_payload()})
    (root / "state.json").write_text(
        json.dumps(original, ensure_ascii=False), encoding="utf-8"
    )
    before = (root / "state.json").read_bytes()

    client = TestClient(create_tasks_app(root))

    # 读路径：v2 数据可读；Task 新字段为 null
    detail = client.get(f"/api/v1/tasks/{TASK_ID}")
    assert detail.status_code == 200, detail.text
    task = detail.json()["task"]
    assert task["goalId"] is None
    assert task["occurrenceOf"] is None
    assert task["planRevision"] is None
    assert _read_payload(root)["schemaVersion"] == 2

    # 首次写操作：v2 → v3，.bak 为升级前原文
    created = client.post(
        "/api/v1/goals",
        json={
            "kind": "habit",
            "title": "晨跑",
            "startDate": "2026-10-20",
            "recurrence": {"freq": "daily", "weekdays": []},
        },
    )
    assert created.status_code == 201, created.text
    habit_id = created.json()["goal"]["id"]

    on_disk = _read_payload(root)
    assert on_disk["schemaVersion"] == 3
    assert set(on_disk["goals"]) == {GOAL_ID, habit_id}
    _assert_original_task_preserved(on_disk["tasks"][TASK_ID], _task_payload())
    assert on_disk["sources"] == original["sources"]
    assert (root / "state.json.bak").read_bytes() == before
