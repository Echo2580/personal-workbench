"""构造样本测试 T04-B 提醒实体。

所有数据均为实体测试的构造样本，不代表真实提取或保存结果。
"""

import pytest
from pydantic import ValidationError

from app.modules.tasks.domain import Reminder


VERSION = "55555555-5555-4555-8555-555555555555"
STAMP = "2026-10-20T08:00:00+08:00"
LATER = "2026-10-20T12:30:00+08:00"

NONE = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": None,
}

MANUAL_SCHEDULED = {
    "mode": "manual",
    "requestedAt": STAMP,
    "scheduledAt": STAMP,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "scheduled",
    "acknowledgedAt": None,
    "revision": VERSION,
}

RELATIVE_SCHEDULED = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": "2026-10-20T09:30:00+08:00",
    "relativeTo": "due",
    "offsetMinutes": 30,
    "state": "scheduled",
    "acknowledgedAt": None,
    "revision": VERSION,
}

RELATIVE_BLOCKED = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": "start",
    "offsetMinutes": 15,
    "state": "blocked",
    "acknowledgedAt": None,
    "revision": VERSION,
}

MANUAL_BLOCKED = {
    "mode": "manual",
    "requestedAt": STAMP,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "blocked",
    "acknowledgedAt": None,
    "revision": VERSION,
}

ACKNOWLEDGED = {
    "mode": "manual",
    "requestedAt": STAMP,
    "scheduledAt": STAMP,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "acknowledged",
    "acknowledgedAt": LATER,
    "revision": VERSION,
}

EXPIRED = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": "2026-10-20T09:30:00+08:00",
    "relativeTo": "due",
    "offsetMinutes": 30,
    "state": "expired",
    "acknowledgedAt": None,
    "revision": VERSION,
}

CANCELLED = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": "2026-10-20T09:30:00+08:00",
    "relativeTo": "due",
    "offsetMinutes": 30,
    "state": "cancelled",
    "acknowledgedAt": None,
    "revision": VERSION,
}

CANCELLED_NO_PLAN = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": "due",
    "offsetMinutes": 30,
    "state": "cancelled",
    "acknowledgedAt": None,
    "revision": VERSION,
}


def test_reminder_modes_and_states():
    for payload in (
        NONE,
        MANUAL_SCHEDULED,
        RELATIVE_SCHEDULED,
        RELATIVE_BLOCKED,
        MANUAL_BLOCKED,
        ACKNOWLEDGED,
        EXPIRED,
        CANCELLED,
        CANCELLED_NO_PLAN,
    ):
        assert Reminder.model_validate(payload).model_dump(
            mode="json", by_alias=True
        ) == payload

    # 模式不完整或组合非法均失败。
    invalid = [
        {**NONE, "requestedAt": STAMP},                      # none 混入时间
        {**NONE, "state": "scheduled"},                       # none 却非 not_set
        {**NONE, "mode": "manual"},                          # manual 缺 requestedAt
        {**MANUAL_SCHEDULED, "relativeTo": "due"},            # manual 带基准
        {**MANUAL_SCHEDULED, "offsetMinutes": 5},             # manual 带偏移
        {**MANUAL_SCHEDULED, "state": "not_set"},             # 非 none 却 not_set
        {**RELATIVE_SCHEDULED, "requestedAt": STAMP},         # relative 带 requestedAt
        {**RELATIVE_SCHEDULED, "relativeTo": None},           # relative 缺基准
        {**RELATIVE_SCHEDULED, "offsetMinutes": None},        # relative 缺偏移
        {**RELATIVE_SCHEDULED, "offsetMinutes": 0},           # 零偏移
        {**RELATIVE_SCHEDULED, "offsetMinutes": -5},          # 负偏移
        {**RELATIVE_SCHEDULED, "offsetMinutes": True},        # bool 偏移
        {**RELATIVE_SCHEDULED, "offsetMinutes": "30"},        # 字符串偏移
        {**RELATIVE_SCHEDULED, "relativeTo": "when"},         # 非法基准
        {**NONE, "mode": "unknown"},
        {**NONE, "state": "unknown"},
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            Reminder.model_validate(payload)


def test_reminder_history_fields():
    # scheduled/acknowledged/expired 缺 scheduledAt 失败。
    for base in (MANUAL_SCHEDULED, ACKNOWLEDGED, EXPIRED):
        with pytest.raises(ValidationError):
            Reminder.model_validate({**base, "scheduledAt": None})
    # blocked 带 scheduledAt 失败。
    with pytest.raises(ValidationError):
        Reminder.model_validate({**RELATIVE_BLOCKED, "scheduledAt": STAMP})
    with pytest.raises(ValidationError):
        Reminder.model_validate({**MANUAL_BLOCKED, "scheduledAt": STAMP})
    # not_set 带 scheduledAt 失败。
    with pytest.raises(ValidationError):
        Reminder.model_validate({**NONE, "scheduledAt": STAMP})
    # acknowledged 缺 acknowledgedAt、其他状态带 acknowledgedAt 均失败。
    with pytest.raises(ValidationError):
        Reminder.model_validate({**ACKNOWLEDGED, "acknowledgedAt": None})
    for base in (
        NONE,
        MANUAL_SCHEDULED,
        RELATIVE_SCHEDULED,
        RELATIVE_BLOCKED,
        EXPIRED,
        CANCELLED,
    ):
        with pytest.raises(ValidationError):
            Reminder.model_validate({**base, "acknowledgedAt": LATER})
    # manual 非空 scheduledAt 与 requestedAt 表示不同时刻失败。
    with pytest.raises(ValidationError):
        Reminder.model_validate({**MANUAL_SCHEDULED, "scheduledAt": LATER})
    with pytest.raises(ValidationError):
        Reminder.model_validate(
            {
                **MANUAL_SCHEDULED,
                "requestedAt": STAMP,
                "scheduledAt": "2026-10-20T08:00:00.5+08:00",
            }
        )
    # manual 终态保留历史：scheduledAt 与 requestedAt 同一时刻仍通过。
    assert Reminder.model_validate(
        {**ACKNOWLEDGED, "scheduledAt": STAMP}
    ).scheduled_at == STAMP
    # cancelled 的 scheduledAt 可为最后时刻或 null。
    assert Reminder.model_validate(CANCELLED).scheduled_at is not None
    assert Reminder.model_validate(CANCELLED_NO_PLAN).scheduled_at is None
    # manual cancelled 也可保留 requestedAt 历史。
    assert (
        Reminder.model_validate(
            {**CANCELLED, "mode": "manual", "requestedAt": STAMP,
             "relativeTo": None, "offsetMinutes": None,
             "scheduledAt": STAMP}
        ).requested_at
        == STAMP
    )

    # 非法时刻与 UUID 失败。
    for bad in ("2026-10-20T08:00:00", "2026-10-20T08:00:00Z", "not-a-time"):
        with pytest.raises(ValidationError):
            Reminder.model_validate({**MANUAL_SCHEDULED, "requestedAt": bad})
        with pytest.raises(ValidationError):
            Reminder.model_validate({**ACKNOWLEDGED, "acknowledgedAt": bad})
    for bad in ("ABCDEFAB-ABCD-4ABC-8ABC-ABCDEFABCDEF", "not-a-uuid", ""):
        with pytest.raises(ValidationError):
            Reminder.model_validate({**MANUAL_SCHEDULED, "revision": bad})
    # revision=null 允许（草稿上下文）。
    assert Reminder.model_validate({**MANUAL_SCHEDULED, "revision": None}).revision is None


def test_reminder_required_keys_and_round_trip():
    for payload in (
        NONE,
        MANUAL_SCHEDULED,
        RELATIVE_SCHEDULED,
        RELATIVE_BLOCKED,
        ACKNOWLEDGED,
        CANCELLED,
        CANCELLED_NO_PLAN,
    ):
        for key in payload:
            incomplete = {k: v for k, v in payload.items() if k != key}
            with pytest.raises(ValidationError):
                Reminder.model_validate(incomplete)
        with pytest.raises(ValidationError):
            Reminder.model_validate({**payload, "unknown": "value"})
        snake = {
            "mode": payload["mode"],
            "requestedAt": payload["requestedAt"],
            "scheduledAt": payload["scheduledAt"],
            "relativeTo": payload["relativeTo"],
            "offsetMinutes": payload["offsetMinutes"],
            "state": payload["state"],
            "acknowledgedAt": payload["acknowledgedAt"],
            "acknowledged_at": payload["acknowledgedAt"],
            "revision": payload["revision"],
        }
        with pytest.raises(ValidationError):
            Reminder.model_validate(snake)

        obj = Reminder.model_validate(payload)
        rebuilt = Reminder.model_validate_json(obj.model_dump_json(by_alias=True))
        assert rebuilt.model_dump(mode="json", by_alias=True) == (
            obj.model_dump(mode="json", by_alias=True)
        )
        # 非法 null：偏移不允许 null 出现在 relative 中已覆盖；此处核对 revision
        # 类型错误与 bool 时刻。
        with pytest.raises(ValidationError):
            Reminder.model_validate({**payload, "mode": True})
