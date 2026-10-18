"""期 3/4/5 规划服务与规划模型适配器单元测试（零真实网络调用）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.modules.tasks.domain import Goal, Task
from app.modules.tasks.services import model_adapter
from app.modules.tasks.services.model_adapter import (
    CREDENTIAL_ENV_VAR,
    DeepSeekGoalPlanner,
    GoalPlanningRequest,
    GoalPlanResult,
    MockGoalPlanner,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.modules.tasks.services.planner import (
    PLAN_DEFAULT_TIME,
    PLAN_HORIZON_DAYS,
    PLAN_MAX_DRAFTS,
    PlanDraftError,
    build_manual_source,
    build_occurrence_days,
    build_occurrence_task_payloads,
    build_planning_request,
    compute_gap_dates,
    existing_task_dates,
    goal_progress,
    normalise_plan_times,
    plan_window,
    run_goal_plan,
    task_goal_date,
    validate_plan_tasks,
)


SHANGHAI = timezone(timedelta(hours=8))
STAMP = "2026-10-18T12:00:00+08:00"
TODAY = date(2026, 10, 18)  # 周日
GOAL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SOURCE_ID = "11111111-1111-4111-8111-111111111111"
VERSION = "55555555-5555-4555-8555-555555555555"

NONE_REMINDER = {
    "mode": "none",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "not_set",
    "acknowledgedAt": None,
    "revision": VERSION,
}


# --------------------------------------------------------------------------- #
# 构造样本
# --------------------------------------------------------------------------- #


def _goal_payload(**overrides):
    payload = {
        "id": GOAL_ID,
        "kind": "plan",
        "title": "考研复习",
        "description": "每天推进一点",
        "startDate": "2026-10-18",
        "targetDate": "2026-10-27",
        "dailyCapacity": 2,
        "constraints": ["每天最多 2 小时"],
        "recurrence": None,
        "status": "active",
        "planRevision": 0,
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }
    payload.update(overrides)
    return payload


def _plan_goal(**overrides) -> Goal:
    return Goal.model_validate(_goal_payload(**overrides))


def _habit_goal(**overrides) -> Goal:
    payload = {
        "id": GOAL_ID,
        "kind": "habit",
        "title": "晨跑",
        "description": None,
        "startDate": "2026-10-18",
        "targetDate": None,
        "dailyCapacity": None,
        "constraints": None,
        "recurrence": {
            "freq": "daily",
            "weekdays": [],
            "time": "07:00",
            "durationMinutes": 30,
        },
        "status": "active",
        "planRevision": 0,
        "createdAt": STAMP,
        "updatedAt": STAMP,
    }
    payload.update(overrides)
    return Goal.model_validate(payload)


def _date_time(day: str, clock: str = "10:00:00") -> dict:
    return {
        "rawExpression": clock,
        "precision": "datetime",
        "resolvedValue": f"{day}T{clock}+08:00",
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def _date_only(day: str) -> dict:
    return {
        "rawExpression": day,
        "precision": "date",
        "resolvedValue": day,
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def _task_id(index: int) -> str:
    return f"33333333-3333-4333-8333-{index:012d}"


def _make_task(
    index: int,
    *,
    goal_id: str | None = GOAL_ID,
    title: str = "任务",
    due: dict | None = None,
    start: dict | None = None,
    status: str = "open",
    occurrence_of: str | None = None,
    plan_revision: int | None = 1,
) -> Task:
    return Task.model_validate(
        {
            "id": _task_id(index),
            "draftId": f"22222222-2222-4222-8222-{index:012d}",
            "sourceId": SOURCE_ID,
            "goalId": goal_id,
            "occurrenceOf": occurrence_of,
            "planRevision": plan_revision,
            "title": title,
            "startTime": start,
            "dueTime": due,
            "requirements": [],
            "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": title,
            "reviewIssues": [],
            "status": status,
            "reminder": NONE_REMINDER,
            "createdAt": STAMP,
            "updatedAt": STAMP,
        }
    )


def _request() -> GoalPlanningRequest:
    return GoalPlanningRequest(
        goal_id=GOAL_ID,
        title="考研复习",
        description="每天推进一点",
        constraints=["每天最多 2 小时"],
        start_date="2026-10-18",
        target_date="2026-10-27",
        daily_capacity=2,
        window_start="2026-10-18",
        window_end="2026-10-27",
        gap_dates=["2026-10-18", "2026-10-19"],
        existing_tasks=[{"date": "2026-10-20", "title": "已有任务"}],
        unavailable_dates=["2026-10-21"],
    )


# --------------------------------------------------------------------------- #
# 自然日 / 空缺计算
# --------------------------------------------------------------------------- #


def test_time_info_date_and_task_goal_date():
    due = _make_task(1, due=_date_time("2026-10-20"), start=_date_only("2026-10-19"))
    assert task_goal_date(due) == date(2026, 10, 20)  # dueTime 优先

    only_start = _make_task(2, start=_date_only("2026-10-19"))
    assert task_goal_date(only_start) == date(2026, 10, 19)

    unresolved = _make_task(
        3,
        due={
            "rawExpression": "周五前",
            "precision": "relative",
            "resolvedValue": None,
            "timeZone": "Asia/Shanghai",
            "status": "needs_confirmation",
        },
    )
    assert task_goal_date(unresolved) is None


def test_plan_window_caps_horizon_and_respects_target():
    goal = _plan_goal(startDate="2026-10-18", targetDate="2027-12-31")
    window = plan_window(goal, TODAY)
    assert window == (TODAY, TODAY + timedelta(days=PLAN_HORIZON_DAYS - 1))

    short = _plan_goal(targetDate="2026-10-22")
    assert plan_window(short, TODAY) == (TODAY, date(2026, 10, 22))

    past = _plan_goal(startDate="2026-10-01", targetDate="2026-10-10")
    assert plan_window(past, TODAY) is None


def test_plan_window_starts_at_max_today_or_start_date():
    future_start = _plan_goal(startDate="2026-10-21", targetDate="2026-10-30")
    assert plan_window(future_start, TODAY) == (
        date(2026, 10, 21),
        date(2026, 10, 30),
    )


def test_existing_task_dates_groups_by_goal_and_date():
    tasks = [
        _make_task(1, due=_date_only("2026-10-19")),
        _make_task(2, start=_date_only("2026-10-19")),
        _make_task(3, due=_date_only("2026-10-20")),
        _make_task(4, goal_id=None, due=_date_only("2026-10-19")),
        _make_task(5, goal_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    ]
    grouped = existing_task_dates(GOAL_ID, tasks)
    assert set(grouped) == {date(2026, 10, 19), date(2026, 10, 20)}
    assert len(grouped[date(2026, 10, 19)]) == 2


def test_compute_gap_dates_skips_existing_and_unavailable():
    goal = _plan_goal(targetDate="2026-10-22")  # 10-18 .. 10-22 共 5 天
    tasks = [_make_task(1, due=_date_only("2026-10-19"))]
    gaps = compute_gap_dates(
        goal, tasks, TODAY, [date(2026, 10, 21)]
    )
    assert gaps == [
        date(2026, 10, 18),
        date(2026, 10, 20),
        date(2026, 10, 22),
    ]


def test_compute_gap_dates_caps_horizon_at_60_days():
    goal = _plan_goal(targetDate="2027-12-31")
    gaps = compute_gap_dates(goal, [], TODAY)
    assert len(gaps) == PLAN_HORIZON_DAYS == 60
    assert gaps[0] == TODAY
    assert gaps[-1] == TODAY + timedelta(days=59)


def test_build_planning_request_contains_goal_context():
    goal = _plan_goal(targetDate="2026-10-22")
    tasks = [_make_task(1, title="已有任务", due=_date_only("2026-10-19"))]
    gaps = compute_gap_dates(goal, tasks, TODAY, [date(2026, 10, 21)])
    request = build_planning_request(
        goal, gaps, tasks, TODAY, [date(2026, 10, 21)]
    )
    assert request.title == "考研复习"
    assert request.daily_capacity == 2
    assert request.gap_dates == ["2026-10-18", "2026-10-20", "2026-10-22"]
    assert request.existing_tasks == [
        {"date": "2026-10-19", "title": "已有任务"}
    ]
    assert request.unavailable_dates == ["2026-10-21"]


# --------------------------------------------------------------------------- #
# run_goal_plan：无缺口不调模型 / 补空缺 / 上限
# --------------------------------------------------------------------------- #


def test_run_goal_plan_without_gaps_does_not_call_model():
    goal = _plan_goal(targetDate="2026-10-19")
    tasks = [
        _make_task(1, due=_date_only("2026-10-18")),
        _make_task(2, due=_date_only("2026-10-19")),
    ]
    model = MockGoalPlanner(tasks=[{"title": "不应出现"}])

    outcome = run_goal_plan(goal, tasks, model, TODAY)

    assert outcome.model_called is False
    assert outcome.drafts == []
    assert outcome.raw_count == 0
    assert outcome.dropped == 0
    assert model.calls == []


def test_run_goal_plan_fills_only_gap_dates_and_counts_model_call():
    """模型返回的越界/重复日期被过滤；只有空缺日进入 drafts。"""
    goal = _plan_goal(targetDate="2026-10-22")
    tasks = [_make_task(1, due=_date_only("2026-10-19"))]
    model = MockGoalPlanner(
        target_date="2027-01-01",
        tasks=[
            {
                "title": "做数学",
                "startTime": None,
                "dueTime": _date_only("2026-10-18"),
                "requirements": ["2 小时"],
            },
            {
                "title": "背单词",
                "startTime": None,
                "dueTime": _date_only("2026-10-19"),  # 已有任务日 → 丢弃
                "requirements": [],
            },
            {
                "title": "做真题",
                "startTime": _date_time("2026-10-20", "09:00:00"),
                "dueTime": None,
                "requirements": [],
            },
        ],
    )

    outcome = run_goal_plan(goal, tasks, model, TODAY)

    assert outcome.model_called is True
    assert outcome.suggested_target_date == "2027-01-01"
    assert [draft["title"] for draft in outcome.drafts] == ["做数学", "做真题"]
    assert [draft["plannedDate"] for draft in outcome.drafts] == [
        "2026-10-18",
        "2026-10-20",
    ]
    # 期 3.3：反馈模型返回条数与丢弃条数（已有任务日被丢弃）
    assert outcome.raw_count == 3
    assert outcome.dropped == 1
    assert len(model.calls) == 1
    assert model.calls[0].gap_dates == [
        "2026-10-18",
        "2026-10-20",
        "2026-10-21",
        "2026-10-22",
    ]


def test_run_goal_plan_reports_all_dropped_without_raising():
    """全部丢弃由 API 层转 502；service 层如实返回 raw_count/dropped 供上层判断。"""
    goal = _plan_goal(targetDate="2026-10-20")
    model = MockGoalPlanner(
        tasks=[
            {"title": "没有日期的任务一"},
            {"title": "没有日期的任务二"},
        ]
    )
    outcome = run_goal_plan(goal, [], model, TODAY)

    assert outcome.model_called is True
    assert outcome.drafts == []
    assert outcome.raw_count == 2
    assert outcome.dropped == 2


def test_run_goal_plan_rejects_invalid_suggested_target_date():
    goal = _plan_goal(targetDate="2026-10-20")
    model = MockGoalPlanner(target_date="明年六月", tasks=[])
    with pytest.raises(PlanDraftError):
        run_goal_plan(goal, [], model, TODAY)
    assert len(model.calls) == 1


# --------------------------------------------------------------------------- #
# validate_plan_tasks：容量 / 总量上限 / 字段校验
# --------------------------------------------------------------------------- #


def _raw_task(title: str, day: str) -> dict:
    return {
        "title": title,
        "startTime": None,
        "dueTime": _date_only(day),
        "requirements": [],
    }


def test_validate_plan_tasks_respects_daily_capacity():
    gaps = [date(2026, 10, 18), date(2026, 10, 19)]
    raw = [
        _raw_task("a", "2026-10-18"),
        _raw_task("b", "2026-10-18"),
        _raw_task("c", "2026-10-18"),  # 超过容量 2 → 丢弃
        _raw_task("d", "2026-10-19"),
    ]
    result = validate_plan_tasks(raw, gaps, daily_capacity=2)
    assert [draft["title"] for draft in result.drafts] == ["a", "b", "d"]
    assert result.raw_count == 4
    assert result.dropped == 1


def test_validate_plan_tasks_caps_total_drafts_at_120():
    start = date(2026, 10, 18)
    gaps = [start + timedelta(days=offset) for offset in range(60)]
    raw = [
        _raw_task(f"任务 {index}", gaps[index % 60].isoformat())
        for index in range(130)
    ]
    result = validate_plan_tasks(raw, gaps, daily_capacity=5)
    assert len(result.drafts) == PLAN_MAX_DRAFTS == 120
    assert result.raw_count == 130
    assert result.dropped == 10


def test_validate_plan_tasks_normalises_times_and_requirements():
    gaps = [date(2026, 10, 18)]
    raw = [
        {
            "title": "  做数学  ",
            "startTime": {
                "rawExpression": "09:00",
                "precision": "datetime",
                "resolvedValue": "2026-10-18T09:00:00+08:00",
                "status": "resolved",
            },
            "dueTime": None,
            "requirements": ["带草稿纸", "  ", "计时"],
        }
    ]
    result = validate_plan_tasks(raw, gaps, daily_capacity=2)
    assert len(result.drafts) == 1
    assert result.raw_count == 1
    assert result.dropped == 0
    draft = result.drafts[0]
    assert draft["title"] == "做数学"
    assert draft["plannedDate"] == "2026-10-18"
    assert draft["startTime"]["timeZone"] == "Asia/Shanghai"
    assert draft["requirements"] == ["带草稿纸", "计时"]
    assert draft["draftId"]
    assert draft["dueTime"] is None


# ---- 期 3.1：缺时刻补 dueTime=plannedDate 20:00 +08:00 --------------------- #


def test_validate_plan_tasks_supplements_due_time_when_clock_missing():
    gaps = [date(2026, 10, 18)]
    raw = [
        {
            "title": "做数学",
            "startTime": None,
            "dueTime": _date_only("2026-10-18"),  # 只有日期、没有时刻
            "requirements": [],
        }
    ]
    draft = validate_plan_tasks(raw, gaps, daily_capacity=2).drafts[0]
    assert draft["startTime"] is None
    assert draft["dueTime"] == {
        "rawExpression": "2026-10-18",
        "precision": "datetime",
        "resolvedValue": f"2026-10-18T{PLAN_DEFAULT_TIME}+08:00",
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }


def test_validate_plan_tasks_supplements_from_date_only_start_time():
    gaps = [date(2026, 10, 19)]
    raw = [
        {
            "title": "背单词",
            "startTime": _date_only("2026-10-19"),
            "dueTime": None,
            "requirements": [],
        }
    ]
    draft = validate_plan_tasks(raw, gaps, daily_capacity=2).drafts[0]
    # 只有日期的时间统一挪到 dueTime 并补 20:00；不再给 startTime
    assert draft["startTime"] is None
    assert draft["dueTime"]["precision"] == "datetime"
    assert draft["dueTime"]["resolvedValue"] == f"2026-10-19T{PLAN_DEFAULT_TIME}+08:00"


def test_validate_plan_tasks_keeps_concrete_due_datetime():
    gaps = [date(2026, 10, 18)]
    raw = [
        {
            "title": "做真题",
            "startTime": None,
            "dueTime": {
                "rawExpression": "18:30",
                "precision": "datetime",
                "resolvedValue": "2026-10-18T18:30:00+08:00",
                "status": "resolved",
            },
            "requirements": [],
        }
    ]
    draft = validate_plan_tasks(raw, gaps, daily_capacity=2).drafts[0]
    assert draft["dueTime"]["resolvedValue"] == "2026-10-18T18:30:00+08:00"
    assert draft["startTime"] is None


def test_validate_plan_tasks_naive_datetime_uses_shanghai():
    gaps = [date(2026, 10, 18)]
    raw = [
        {
            "title": "做数学",
            "startTime": {
                "rawExpression": "09:00",
                "precision": "datetime",
                "resolvedValue": "2026-10-18T09:00:00",  # 缺时区
                "status": "resolved",
            },
            "dueTime": None,
            "requirements": [],
        }
    ]
    draft = validate_plan_tasks(raw, gaps, daily_capacity=2).drafts[0]
    assert draft["startTime"]["resolvedValue"] == "2026-10-18T09:00:00+08:00"
    assert draft["dueTime"] is None


def test_normalise_plan_times_cases():
    planned = date(2026, 10, 18)
    concrete = {
        "rawExpression": "09:00",
        "precision": "datetime",
        "resolvedValue": "2026-10-18T09:00:00+08:00",
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }
    date_only = _date_only("2026-10-18")

    # 两个都具体：原样保留
    assert normalise_plan_times(concrete, concrete, planned) == (concrete, concrete)
    # 只有一个具体：保留它，另一个非具体值置 null
    assert normalise_plan_times(concrete, date_only, planned) == (concrete, None)
    assert normalise_plan_times(date_only, concrete, planned) == (None, concrete)
    # 都没有具体时刻：补 dueTime 20:00；rawExpression 保留原值
    start, due = normalise_plan_times(None, date_only, planned)
    assert start is None
    assert due["resolvedValue"] == f"2026-10-18T{PLAN_DEFAULT_TIME}+08:00"
    assert due["rawExpression"] == "2026-10-18"
    # 完全无时间：rawExpression 用「规划：YYYY-MM-DD」
    start, due = normalise_plan_times(None, None, planned)
    assert start is None
    assert due["rawExpression"] == "规划：2026-10-18"
    # 自然日未知：不做补充，原样返回
    assert normalise_plan_times(None, date_only, None) == (None, date_only)


# ---- 期 3.3：plannedDate 优先 / 全丢可见 / dropped 统计 --------------------- #


def test_planned_date_takes_priority_over_times():
    gaps = [date(2026, 10, 18)]
    raw = [
        {
            "plannedDate": "2026-10-18",
            # 时间字段的日期不在空缺日：若按旧逻辑（due 优先）会被丢弃
            "dueTime": _date_only("2026-10-19"),
            "title": "做数学",
            "requirements": [],
        }
    ]
    result = validate_plan_tasks(raw, gaps, daily_capacity=2)
    assert [draft["plannedDate"] for draft in result.drafts] == ["2026-10-18"]
    assert result.raw_count == 1
    assert result.dropped == 0


def test_planned_date_outside_gaps_is_dropped():
    gaps = [date(2026, 10, 18)]
    raw = [{"plannedDate": "2026-10-20", "title": "做数学", "requirements": []}]
    result = validate_plan_tasks(raw, gaps, daily_capacity=2)
    assert result.drafts == []
    assert result.raw_count == 1
    assert result.dropped == 1


def test_task_without_any_date_is_dropped():
    gaps = [date(2026, 10, 18)]
    raw = [{"title": "做数学", "startTime": None, "dueTime": None, "requirements": []}]
    result = validate_plan_tasks(raw, gaps, daily_capacity=2)
    assert result.drafts == []
    assert result.raw_count == 1
    assert result.dropped == 1


def test_partial_missing_dates_keeps_valid_and_counts_dropped():
    gaps = [date(2026, 10, 18), date(2026, 10, 19)]
    raw = [
        {"plannedDate": "2026-10-18", "title": "有效任务", "requirements": []},
        {"title": "无日期任务", "requirements": []},
    ]
    result = validate_plan_tasks(raw, gaps, daily_capacity=2)
    assert [draft["title"] for draft in result.drafts] == ["有效任务"]
    assert result.raw_count == 2
    assert result.dropped == 1
    # 无时刻的 plannedDate 任务仍按 20:00 补 dueTime
    assert result.drafts[0]["dueTime"]["resolvedValue"] == (
        f"2026-10-18T{PLAN_DEFAULT_TIME}+08:00"
    )


def test_invalid_planned_date_format_raises():
    with pytest.raises(PlanDraftError):
        validate_plan_tasks(
            [{"plannedDate": "明天", "title": "做数学"}],
            [date(2026, 10, 18)],
            daily_capacity=2,
        )


@pytest.mark.parametrize(
    "raw",
    [
        ["不是对象"],
        [{"title": "   ", "dueTime": _date_only("2026-10-18")}],
        [{"title": "x", "dueTime": "2026-10-18"}],
        [{"title": "x", "dueTime": {"precision": "datetime"}}],
        [{"title": "x", "dueTime": _date_only("2026-10-18"), "requirements": "abc"}],
        [{"title": "x", "dueTime": _date_only("2026-10-18"), "requirements": [1]}],
        [
            {
                "title": "x",
                "dueTime": {
                    "rawExpression": "x",
                    "precision": "datetime",
                    "resolvedValue": "2026-10-18T09:00:00+00:00",  # 非 +08:00
                    "status": "resolved",
                },
            }
        ],
    ],
)
def test_validate_plan_tasks_rejects_invalid_model_output(raw):
    with pytest.raises(PlanDraftError):
        validate_plan_tasks(raw, [date(2026, 10, 18)], daily_capacity=2)


# --------------------------------------------------------------------------- #
# 习惯实例
# --------------------------------------------------------------------------- #


def test_build_occurrence_days_daily_from_start_date():
    habit = _habit_goal(startDate=(TODAY + timedelta(days=1)).isoformat())
    days = build_occurrence_days(habit, TODAY, set())
    assert days[0] == TODAY + timedelta(days=1)
    assert len(days) == 13  # 未来 14 天里扣掉早于 startDate 的今天


def test_build_occurrence_days_weekly_filters_weekdays():
    habit = _habit_goal(
        recurrence={
            "freq": "weekly",
            "weekdays": [1, 3],
            "time": "07:00",
            "durationMinutes": None,
        }
    )
    days = build_occurrence_days(habit, TODAY, set())
    expected = {
        TODAY + timedelta(days=offset)
        for offset in range(14)
        if (TODAY + timedelta(days=offset)).isoweekday() in (1, 3)
    }
    assert set(days) == expected


def test_build_occurrence_days_skips_existing_dates():
    habit = _habit_goal()
    existing = {TODAY, TODAY + timedelta(days=2)}
    days = build_occurrence_days(habit, TODAY, existing)
    assert TODAY not in days
    assert TODAY + timedelta(days=2) not in days
    assert len(days) == 12


def test_build_occurrence_task_payloads_uses_recurrence_time_as_due_time():
    """期 3.2：dueTime 用 recurrence.time 的具体时刻；startTime=null；
    durationMinutes 只进执行要求文案，不再改时间字段。"""
    habit = _habit_goal()
    day = TODAY + timedelta(days=1)
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=SHANGHAI)
    payloads = build_occurrence_task_payloads(
        habit, [day], SOURCE_ID, now
    )
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["goalId"] == GOAL_ID
    assert payload["occurrenceOf"] == GOAL_ID
    assert payload["planRevision"] is None
    assert payload["startTime"] is None
    assert payload["dueTime"] == {
        "rawExpression": "07:00",
        "precision": "datetime",
        "resolvedValue": f"{day}T07:00:00+08:00",
        "timeZone": "Asia/Shanghai",
        "status": "resolved",
    }
    assert payload["requirements"] == ["约 30 分钟"]
    assert payload["status"] == "open"
    Task.model_validate(payload)


def test_build_occurrence_task_payloads_without_time_uses_2000():
    """期 3.2：habit 未配置 recurrence.time 时 dueTime 补 20:00 +08:00。"""
    habit = _habit_goal(
        recurrence={
            "freq": "daily",
            "weekdays": [],
            "time": None,
            "durationMinutes": None,
        }
    )
    day = TODAY + timedelta(days=2)
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=SHANGHAI)
    payload = build_occurrence_task_payloads(habit, [day], SOURCE_ID, now)[0]

    assert payload["startTime"] is None
    assert payload["dueTime"]["precision"] == "datetime"
    assert payload["dueTime"]["status"] == "resolved"
    assert payload["dueTime"]["resolvedValue"] == f"{day}T20:00:00+08:00"
    assert payload["requirements"] == []
    assert Task.model_validate(payload).due_time is not None


# --------------------------------------------------------------------------- #
# 进度
# --------------------------------------------------------------------------- #


def test_goal_progress_counts_total_completed_overdue():
    tasks = [
        # 逾期：open 且日期早于今天
        _make_task(1, due=_date_only("2026-10-17")),
        # 已完成不计逾期
        _make_task(2, due=_date_only("2026-10-16"), status="completed"),
        # 今天及未来不算逾期
        _make_task(3, due=_date_only("2026-10-18")),
        _make_task(4, due=_date_only("2026-10-25")),
        # 无日期不逾期
        _make_task(5),
        # 其他 goal 不计入
        _make_task(
            6,
            goal_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            due=_date_only("2026-10-01"),
        ),
    ]
    progress = goal_progress(GOAL_ID, tasks, TODAY)
    assert progress == {"total": 5, "completed": 1, "overdue": 1}


def test_build_manual_source_is_manual_kind_and_hashes_text():
    now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=SHANGHAI)
    payload = build_manual_source("长期任务规划：考研复习", now)
    assert payload["kind"] == "manual"
    assert payload["originalText"] == "长期任务规划：考研复习"
    assert payload["relativePath"] is None
    assert payload["mimeType"] == "text/plain; charset=utf-8"
    assert payload["messageDate"] == "2026-10-18"
    assert len(payload["contentSha256"]) == 64


# --------------------------------------------------------------------------- #
# DeepSeekGoalPlanner（httpx 桩，零真实网络）
# --------------------------------------------------------------------------- #


class _StubResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _StubClient:
    def __init__(self, recorder: dict, response: _StubResponse):
        self._recorder = recorder
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, headers=None, json=None):
        self._recorder["url"] = url
        self._recorder["headers"] = dict(headers or {})
        self._recorder["json"] = json
        return self._response


def _stub_http(monkeypatch, response: _StubResponse) -> dict:
    recorder: dict = {}
    monkeypatch.setattr(
        model_adapter.httpx,
        "Client",
        lambda timeout=None: _StubClient(recorder, response),
    )
    return recorder


def _ok(content: str) -> _StubResponse:
    return _StubResponse(200, {"choices": [{"message": {"content": content}}]})


def test_deepseek_goal_planner_uses_flash_and_parses(monkeypatch):
    recorder = _stub_http(
        monkeypatch,
        _ok(
            json.dumps(
                {
                    "targetDate": "2027-07-01",
                    "tasks": [
                        {
                            "title": "做数学",
                            "startTime": None,
                            "dueTime": None,
                            "requirements": [],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ),
    )
    planner = DeepSeekGoalPlanner(api_key="sk-test-fake")

    result = planner.plan_goal(_request())

    assert isinstance(result, GoalPlanResult)
    assert result.target_date == "2027-07-01"
    assert result.tasks[0]["title"] == "做数学"
    body = recorder["json"]
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    system, user = body["messages"]
    assert "计划排期" in system["content"]
    assert "plannedDate" in system["content"]
    assert "考研复习" in user["content"]
    assert "2026-10-18" in user["content"]
    assert "2026-10-21" in user["content"]  # 不可用日
    assert "已有任务" in user["content"]


def test_deepseek_goal_planner_missing_key_raises_without_value(monkeypatch):
    planner = DeepSeekGoalPlanner(api_key="")
    with pytest.raises(ModelUnavailableError) as excinfo:
        planner.plan_goal(_request())
    message = str(excinfo.value)
    assert CREDENTIAL_ENV_VAR in message
    assert "sk-" not in message


def test_deepseek_goal_planner_timeout(monkeypatch):
    _stub_http(monkeypatch, _ok('{"tasks": []}'))

    def _boom(self, *args, **kwargs):
        raise model_adapter.httpx.TimeoutException("timeout")

    monkeypatch.setattr(_StubClient, "post", _boom)

    with pytest.raises(ModelTimeoutError):
        DeepSeekGoalPlanner(api_key="sk-test-fake").plan_goal(_request())


def test_deepseek_goal_planner_http_error_is_unavailable(monkeypatch):
    _stub_http(monkeypatch, _StubResponse(500, {"error": "boom"}))
    with pytest.raises(ModelUnavailableError):
        DeepSeekGoalPlanner(api_key="sk-test-fake").plan_goal(_request())


@pytest.mark.parametrize(
    "content",
    [
        "不是 JSON",
        '{"tasks": "not-a-list"}',
        '{"tasks": [], "targetDate": 20270101}',
    ],
)
def test_deepseek_goal_planner_invalid_output(monkeypatch, content):
    _stub_http(monkeypatch, _ok(content))
    with pytest.raises(ModelOutputInvalidError):
        DeepSeekGoalPlanner(api_key="sk-test-fake").plan_goal(_request())


def test_deepseek_goal_planner_output_not_object(monkeypatch):
    _stub_http(monkeypatch, _ok("[]"))
    with pytest.raises(ModelOutputInvalidError):
        DeepSeekGoalPlanner(api_key="sk-test-fake").plan_goal(_request())


# --------------------------------------------------------------------------- #
# MockGoalPlanner
# --------------------------------------------------------------------------- #


def test_mock_goal_planner_returns_preset_and_records_calls():
    model = MockGoalPlanner(
        tasks=[{"title": "做数学"}], target_date="2027-01-01"
    )
    result = model.plan_goal(_request())
    assert result.target_date == "2027-01-01"
    assert result.tasks == [{"title": "做数学"}]
    assert len(model.calls) == 1
    assert model.calls[0].goal_id == GOAL_ID


def test_mock_goal_planner_raises_preset_error():
    model = MockGoalPlanner(error=ModelTimeoutError("超时"))
    with pytest.raises(ModelTimeoutError):
        model.plan_goal(_request())


def test_mock_goal_planner_result_override():
    model = MockGoalPlanner(
        result=GoalPlanResult(target_date=None, tasks=[]),
        tasks=[{"title": "不会用到"}],
    )
    result = model.plan_goal(_request())
    assert result.tasks == []
