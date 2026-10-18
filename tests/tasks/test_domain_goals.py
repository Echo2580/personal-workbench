"""构造样本测试 Goal / Recurrence 领域模型：严格类型、camelCase 别名与互斥校验。

所有数据均为实体测试的构造样本，不代表真实业务数据。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.tasks.domain import Goal, Recurrence


STAMP = "2026-10-18T12:00:00+08:00"
GOAL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _recurrence(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "freq": "daily",
        "weekdays": [],
        "time": "07:00",
        "durationMinutes": 30,
    }
    payload.update(overrides)
    return payload


def _plan(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": GOAL_ID,
        "kind": "plan",
        "title": "考研复习",
        "description": "每天推进一点",
        "startDate": "2026-10-20",
        "targetDate": "2027-06-30",
        "dailyCapacity": 3,
        "constraints": ["每天最多 2 小时"],
        "recurrence": None,
        "status": "active",
        "planRevision": 0,
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }
    payload.update(overrides)
    return payload


def _habit(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": GOAL_ID,
        "kind": "habit",
        "title": "晨跑",
        "description": None,
        "startDate": "2026-10-20",
        "targetDate": None,
        "dailyCapacity": None,
        "constraints": None,
        "recurrence": _recurrence(),
        "status": "active",
        "planRevision": 0,
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# 正常形态与别名
# --------------------------------------------------------------------------- #


def test_plan_goal_dumps_camel_case_aliases():
    goal = Goal.model_validate(_plan())

    assert goal.kind == "plan"
    assert goal.target_date == "2027-06-30"
    assert goal.daily_capacity == 3
    assert goal.recurrence is None

    dumped = goal.model_dump(mode="json", by_alias=True)
    assert set(dumped) == {
        "id",
        "kind",
        "title",
        "description",
        "startDate",
        "targetDate",
        "dailyCapacity",
        "constraints",
        "recurrence",
        "status",
        "planRevision",
        "createdAt",
        "updatedAt",
    }
    assert dumped["targetDate"] == "2027-06-30"
    assert dumped["dailyCapacity"] == 3
    assert dumped["planRevision"] == 0
    # 内部 snake_case 名不得出现在对外载荷里
    assert "start_date" not in dumped
    assert "target_date" not in dumped


def test_habit_goal_accepts_weekly_recurrence():
    weekly = _recurrence(freq="weekly", weekdays=[1, 3, 5], time=None, durationMinutes=None)
    goal = Goal.model_validate(_habit(recurrence=weekly))

    assert goal.target_date is None
    assert goal.recurrence is not None
    assert goal.recurrence.freq == "weekly"
    assert goal.recurrence.weekdays == [1, 3, 5]
    assert goal.recurrence.duration_minutes is None


def test_habit_may_declare_daily_capacity():
    # 任务单：dailyCapacity 对 plan 必填、对 habit 可空（不强制 null）
    goal = Goal.model_validate(_habit(dailyCapacity=2))
    assert goal.daily_capacity == 2


# --------------------------------------------------------------------------- #
# plan / habit 互斥字段
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("overrides", "hint"),
    [
        ({"targetDate": None}, "targetDate"),
        ({"dailyCapacity": None}, "dailyCapacity"),
        ({"recurrence": _recurrence()}, "recurrence"),
    ],
)
def test_plan_requires_plan_fields_and_no_recurrence(overrides, hint):
    with pytest.raises(ValidationError) as excinfo:
        Goal.model_validate(_plan(**overrides))
    assert hint in str(excinfo.value)


@pytest.mark.parametrize(
    ("overrides", "hint"),
    [
        ({"targetDate": "2026-11-01"}, "targetDate"),
        ({"recurrence": None}, "recurrence"),
    ],
)
def test_habit_requires_null_target_date_and_recurrence(overrides, hint):
    with pytest.raises(ValidationError) as excinfo:
        Goal.model_validate(_habit(**overrides))
    assert hint in str(excinfo.value)


def test_plan_target_date_must_not_precede_start_date():
    # 期 3 追加的区间校验：plan 的 startDate ≤ targetDate
    with pytest.raises(ValidationError) as excinfo:
        Goal.model_validate(_plan(targetDate="2026-10-19"))
    assert "precede" in str(excinfo.value)


def test_plan_target_date_may_equal_start_date():
    goal = Goal.model_validate(_plan(targetDate="2026-10-20"))
    assert goal.target_date == goal.start_date


# --------------------------------------------------------------------------- #
# 严格模型：extra=forbid、strict=True
# --------------------------------------------------------------------------- #


def test_goal_rejects_extra_fields():
    with pytest.raises(ValidationError) as excinfo:
        Goal.model_validate(_plan(priority="高"))
    assert any(
        error["type"] == "extra_forbidden" for error in excinfo.value.errors()
    )


def test_goal_rejects_snake_case_keys():
    payload = _plan()
    payload.pop("startDate")
    payload["start_date"] = "2026-10-20"
    with pytest.raises(ValidationError):
        Goal.model_validate(payload)


@pytest.mark.parametrize("value", ["3", 3.0, True, None])
def test_daily_capacity_is_strict_int(value):
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(dailyCapacity=value))


@pytest.mark.parametrize("value", ["0", -1, 1.5, True])
def test_plan_revision_is_strict_non_negative_int(value):
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(planRevision=value))


@pytest.mark.parametrize("value", ["active", "paused", "archived", "done"])
def test_status_literal(value):
    if value in ("active", "done", "archived"):
        assert Goal.model_validate(_plan(status=value)).status == value
    else:
        with pytest.raises(ValidationError):
            Goal.model_validate(_plan(status=value))


def test_kind_literal():
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(kind="todo"))


@pytest.mark.parametrize("value", ["2026-10-18T12:00:00Z", "2026-10-18T12:00:00+00:00", "2026-10-18"])
def test_timestamps_must_use_shanghai_offset(value):
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(createdAt=value))
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(updatedAt=value))


@pytest.mark.parametrize("value", ["AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "not-a-uuid"])
def test_id_must_be_lowercase_uuid(value):
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(id=value))


# --------------------------------------------------------------------------- #
# title / description / dates / constraints
# --------------------------------------------------------------------------- #


def test_title_is_trimmed_and_bounded():
    assert Goal.model_validate(_plan(title="  考研复习  ")).title == "考研复习"
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(title="   "))
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(title="x" * 201))
    assert Goal.model_validate(_plan(title="x" * 200)).title == "x" * 200


def test_description_must_not_be_blank():
    assert Goal.model_validate(_plan(description=None)).description is None
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(description="   "))


@pytest.mark.parametrize(
    "value", ["2026-13-01", "2026-02-30", "2026/10/20", "20261020", "2026-10-20T00:00:00+08:00"]
)
def test_dates_must_be_real_yyyy_mm_dd(value):
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(startDate=value))
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(targetDate=value))


def test_constraints_must_not_contain_blank_items():
    assert Goal.model_validate(_plan(constraints=None)).constraints is None
    assert Goal.model_validate(_plan(constraints=[])).constraints == []
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(constraints=["每天两小时", " "]))
    with pytest.raises(ValidationError):
        Goal.model_validate(_plan(constraints=[""]))


# --------------------------------------------------------------------------- #
# Recurrence
# --------------------------------------------------------------------------- #


def test_recurrence_requires_all_keys():
    # 与既有严格模型一致：可空字段也必须显式出现
    with pytest.raises(ValidationError):
        Recurrence.model_validate({"freq": "daily", "time": None, "durationMinutes": None})


def test_daily_recurrence_must_keep_weekdays_empty():
    assert Recurrence.model_validate(_recurrence(freq="daily", weekdays=[]))
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="daily", weekdays=[1]))


def test_weekly_recurrence_requires_unique_non_empty_weekdays():
    assert Recurrence.model_validate(
        _recurrence(freq="weekly", weekdays=[1, 7])
    ).weekdays == [1, 7]
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="weekly", weekdays=[]))
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="weekly", weekdays=[1, 1]))
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="weekly", weekdays=[1, 3, 5, 1]))


@pytest.mark.parametrize("value", [0, 8, -1])
def test_recurrence_weekdays_range(value):
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="weekly", weekdays=[value]))


@pytest.mark.parametrize("value", ["1", 1.0, True])
def test_recurrence_weekdays_are_strict_ints(value):
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="weekly", weekdays=[value]))


def test_recurrence_time_format():
    for value in ("00:00", "07:00", "23:59", None):
        assert Recurrence.model_validate(_recurrence(time=value)).time == value
    for value in ("24:00", "7:00", "07:60", "0700", "07:00:00"):
        with pytest.raises(ValidationError):
            Recurrence.model_validate(_recurrence(time=value))


@pytest.mark.parametrize("value", [1, 600, None])
def test_recurrence_duration_bounds_ok(value):
    assert (
        Recurrence.model_validate(_recurrence(durationMinutes=value)).duration_minutes
        == value
    )


@pytest.mark.parametrize("value", [0, 601, -5])
def test_recurrence_duration_out_of_bounds(value):
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(durationMinutes=value))


def test_recurrence_freq_literal():
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(freq="monthly"))


def test_recurrence_rejects_extra_fields():
    with pytest.raises(ValidationError):
        Recurrence.model_validate(_recurrence(interval=2))
