"""期 3/4/5 接口回归：AI 规划（两步落库）、习惯实例幂等、进度与 goalId 过滤。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.modules.tasks.app_factory import create_tasks_app
from app.modules.tasks.services.model_adapter import (
    MockGoalPlanner,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)


SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=SHANGHAI)
TODAY = NOW.date()


@pytest.fixture()
def make_client(tmp_path: Path, monkeypatch):
    """构造隔离 TestClient；默认把 goals 模块时钟冻结到 NOW（周日）。"""
    root = tmp_path / "data"

    def _make(planner: MockGoalPlanner | None = None, *, freeze: bool = True):
        app = create_tasks_app(root)
        if planner is not None:
            app.state.goal_planner = planner
        if freeze:
            monkeypatch.setattr(
                "app.modules.tasks.api.goals.current_time", lambda: NOW
            )
        return TestClient(app)

    return _make


def create_plan_goal(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "plan",
        "title": "考研复习",
        "startDate": TODAY.isoformat(),
        "targetDate": (TODAY + timedelta(days=9)).isoformat(),
        "dailyCapacity": 2,
    }
    body.update(overrides)
    response = client.post("/api/v1/goals", json=body)
    assert response.status_code == 201, response.text
    return response.json()["goal"]


def create_habit_goal(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "habit",
        "title": "晨跑",
        "startDate": TODAY.isoformat(),
        "recurrence": {
            "freq": "daily",
            "weekdays": [],
            "time": "07:00",
            "durationMinutes": 30,
        },
    }
    body.update(overrides)
    response = client.post("/api/v1/goals", json=body)
    assert response.status_code == 201, response.text
    return response.json()["goal"]


def plan_task(
    title: str,
    day: date,
    *,
    clock: str | None = None,
    requirements: list[str] | None = None,
    planned_date: date | None = None,
) -> dict[str, Any]:
    """构造模型输出的当日任务：期 3.3 起提示词要求必带 plannedDate。"""
    if clock is None:
        start_time = None
        due_time = {
            "rawExpression": day.isoformat(),
            "precision": "date",
            "resolvedValue": day.isoformat(),
            "status": "resolved",
        }
    else:
        start_time = {
            "rawExpression": clock,
            "precision": "datetime",
            "resolvedValue": f"{day.isoformat()}T{clock}+08:00",
            "status": "resolved",
        }
        due_time = None
    return {
        "plannedDate": (planned_date or day).isoformat(),
        "title": title,
        "startTime": start_time,
        "dueTime": due_time,
        "requirements": requirements or [],
    }


def save_draft(
    title: str,
    *,
    planned_date: date | None = None,
    due_time: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "plannedDate": (planned_date or TODAY).isoformat(),
        "startTime": None,
        "dueTime": due_time,
        "requirements": [],
    }


def _tasks(client: TestClient, goal_id: str) -> list[dict[str, Any]]:
    response = client.get(
        "/api/v1/tasks", params={"status": "all", "goalId": goal_id}
    )
    assert response.status_code == 200, response.text
    return response.json()["tasks"]


# --------------------------------------------------------------------------- #
# POST /goals/{id}/plan：只返回 drafts，不落库
# --------------------------------------------------------------------------- #


def test_plan_returns_drafts_without_writing_tasks(make_client):
    planner = MockGoalPlanner(
        target_date=(TODAY + timedelta(days=20)).isoformat(),
        tasks=[
            plan_task("做数学", TODAY, clock="09:00:00"),
            plan_task("背单词", TODAY + timedelta(days=1)),
        ],
    )
    client = make_client(planner)
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "planRevision",
        "suggestedTargetDate",
        "drafts",
        "rawCount",
        "dropped",
    }
    assert body["planRevision"] == 1
    assert body["suggestedTargetDate"] == (TODAY + timedelta(days=20)).isoformat()
    assert len(body["drafts"]) == 2
    assert body["rawCount"] == 2
    assert body["dropped"] == 0
    for draft in body["drafts"]:
        assert set(draft) == {
            "draftId",
            "plannedDate",
            "title",
            "startTime",
            "dueTime",
            "requirements",
        }
        assert draft["startTime"] is None or (
            draft["startTime"]["timeZone"] == "Asia/Shanghai"
        )
    assert {draft["plannedDate"] for draft in body["drafts"]} == {
        TODAY.isoformat(),
        (TODAY + timedelta(days=1)).isoformat(),
    }
    # 规划只写 goal.planRevision，不写任务
    assert _tasks(client, goal["id"]) == []
    detail = client.get(f"/api/v1/goals/{goal['id']}").json()
    assert detail["goal"]["planRevision"] == 1
    assert len(planner.calls) == 1
    assert planner.calls[0].goal_id == goal["id"]


# ---- 期 3.3：plannedDate 契约 / dropped+rawCount / 全丢 502 ----------------- #


def test_plan_uses_planned_date_without_any_times(make_client):
    """模型按提示词只给 plannedDate（时间可 null）→ 正常出草稿并补 20:00。"""
    day_one = TODAY + timedelta(days=1)
    day_two = TODAY + timedelta(days=3)
    planner = MockGoalPlanner(
        tasks=[plan_task("做数学", day_one), plan_task("背单词", day_two)]
    )
    client = make_client(planner)
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rawCount"] == 2
    assert body["dropped"] == 0
    assert body["planRevision"] == 1
    assert [draft["plannedDate"] for draft in body["drafts"]] == [
        day_one.isoformat(),
        day_two.isoformat(),
    ]
    for draft in body["drafts"]:
        assert draft["startTime"] is None
        assert draft["dueTime"]["resolvedValue"] == (
            f"{draft['plannedDate']}T20:00:00+08:00"
        )

    saved = client.post(
        f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": body["drafts"]}
    ).json()["tasks"]
    assert len(saved) == 2
    hit = client.get(
        "/api/v1/tasks",
        params={
            "status": "all",
            "from": day_one.isoformat(),
            "to": day_one.isoformat(),
        },
    ).json()["tasks"]
    assert len(hit) == 1
    assert hit[0]["dueTime"]["resolvedValue"] == f"{day_one.isoformat()}T20:00:00+08:00"


def test_plan_without_planned_date_falls_back_to_time_dates(make_client):
    """兼容旧模型输出：无 plannedDate 时按 dueTime → startTime 兜底。"""
    planner = MockGoalPlanner(
        tasks=[
            {
                "title": "做数学",
                "startTime": None,
                "dueTime": {
                    "rawExpression": TODAY.isoformat(),
                    "precision": "date",
                    "resolvedValue": TODAY.isoformat(),
                    "status": "resolved",
                },
                "requirements": [],
            }
        ]
    )
    client = make_client(planner)
    goal = create_plan_goal(client)

    body = client.post(f"/api/v1/goals/{goal['id']}/plan").json()

    assert body["rawCount"] == 1
    assert body["dropped"] == 0
    assert body["drafts"][0]["plannedDate"] == TODAY.isoformat()


def test_plan_all_tasks_without_usable_dates_is_502(make_client):
    """模型返回了任务但全部无法定日期 → 502，不能伪装成成功空结果。"""
    planner = MockGoalPlanner(
        tasks=[{"title": "无日期任务一"}, {"title": "无日期任务二"}]
    )
    client = make_client(planner)
    goal = create_plan_goal(client)
    before = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 502, response.text
    error = response.json()["error"]
    assert error["code"] == "plan_validation_failed"
    assert "缺少可用日期" in error["message"]
    after = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]
    assert after["planRevision"] == 0
    assert after["updatedAt"] == before["updatedAt"]
    assert _tasks(client, goal["id"]) == []


def test_plan_partial_missing_dates_keeps_valid_and_reports_dropped(make_client):
    planner = MockGoalPlanner(
        tasks=[
            plan_task("有效任务", TODAY + timedelta(days=1)),
            {"title": "无日期任务"},
        ]
    )
    client = make_client(planner)
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rawCount"] == 2
    assert body["dropped"] == 1
    assert [draft["title"] for draft in body["drafts"]] == ["有效任务"]
    assert body["planRevision"] == 1


def test_plan_model_returns_no_tasks_does_not_increment_revision(make_client):
    """rawCount=0（模型确实没给任务）→ 成功空结果，但不计规划轮次、不写盘。"""
    planner = MockGoalPlanner(tasks=[])
    client = make_client(planner)
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["drafts"] == []
    assert body["rawCount"] == 0
    assert body["dropped"] == 0
    assert body["planRevision"] == 0
    after = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]
    assert after["planRevision"] == 0
    assert after["updatedAt"] == goal["updatedAt"]


def test_plan_supplements_missing_clock_to_due_time(make_client):
    """期 3.1：模型只给日期时，draft/落库任务补 dueTime=plannedDate 20:00 +08:00。"""
    plan_day = TODAY + timedelta(days=1)
    planner = MockGoalPlanner(tasks=[plan_task("背单词", plan_day)])
    client = make_client(planner)
    goal = create_plan_goal(client)

    plan = client.post(f"/api/v1/goals/{goal['id']}/plan").json()
    draft = plan["drafts"][0]
    expected = f"{plan_day.isoformat()}T20:00:00+08:00"
    assert draft["startTime"] is None
    assert draft["dueTime"]["precision"] == "datetime"
    assert draft["dueTime"]["status"] == "resolved"
    assert draft["dueTime"]["resolvedValue"] == expected

    saved = client.post(
        f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": plan["drafts"]}
    ).json()["tasks"][0]
    assert saved["startTime"] is None
    assert saved["dueTime"]["resolvedValue"] == expected

    # 日历/首页依赖 from/to（due 优先）能按计划日命中
    hit = client.get(
        "/api/v1/tasks",
        params={
            "status": "all",
            "from": plan_day.isoformat(),
            "to": plan_day.isoformat(),
        },
    )
    assert [task["id"] for task in hit.json()["tasks"]] == [saved["id"]]
    previous = plan_day - timedelta(days=1)
    miss = client.get(
        "/api/v1/tasks",
        params={
            "status": "all",
            "from": previous.isoformat(),
            "to": previous.isoformat(),
        },
    )
    assert miss.json()["tasks"] == []


def test_plan_keeps_model_concrete_datetime(make_client):
    """模型给出具体 datetime 时原样保留，不再补 20:00。"""
    planner = MockGoalPlanner(tasks=[plan_task("做数学", TODAY, clock="09:00:00")])
    client = make_client(planner)
    goal = create_plan_goal(client)

    draft = client.post(f"/api/v1/goals/{goal['id']}/plan").json()["drafts"][0]
    assert draft["startTime"]["resolvedValue"] == f"{TODAY.isoformat()}T09:00:00+08:00"
    assert draft["dueTime"] is None

    saved = client.post(
        f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": [draft]}
    ).json()["tasks"][0]
    assert saved["startTime"]["resolvedValue"] == f"{TODAY.isoformat()}T09:00:00+08:00"
    assert saved["dueTime"] is None

    hit = client.get(
        "/api/v1/tasks",
        params={"status": "all", "from": TODAY.isoformat(), "to": TODAY.isoformat()},
    )
    assert saved["id"] in {task["id"] for task in hit.json()["tasks"]}


def test_plan_naive_datetime_is_interpreted_as_shanghai(make_client):
    planner = MockGoalPlanner(
        tasks=[
            {
                "title": "做数学",
                "startTime": {
                    "rawExpression": "09:00",
                    "precision": "datetime",
                    "resolvedValue": f"{TODAY.isoformat()}T09:00:00",  # 缺时区
                    "status": "resolved",
                },
                "dueTime": None,
                "requirements": [],
            }
        ]
    )
    client = make_client(planner)
    goal = create_plan_goal(client)

    draft = client.post(f"/api/v1/goals/{goal['id']}/plan").json()["drafts"][0]
    assert draft["startTime"]["resolvedValue"] == f"{TODAY.isoformat()}T09:00:00+08:00"


def test_save_tasks_supplements_missing_clock(make_client):
    """客户端直接提交只有 plannedDate 的草稿，落库时也补 20:00 截止时刻。"""
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)

    task = client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={"drafts": [save_draft("只有日期")]},
    ).json()["tasks"][0]

    assert task["startTime"] is None
    assert task["dueTime"]["resolvedValue"] == f"{TODAY.isoformat()}T20:00:00+08:00"
    assert task["dueTime"]["precision"] == "datetime"


def test_plan_without_gaps_does_not_call_model(make_client):
    planner = MockGoalPlanner(tasks=[plan_task("不应出现", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(
        client,
        startDate=TODAY.isoformat(),
        targetDate=TODAY.isoformat(),
    )
    # 先给今天放一条该目标的任务 → 无缺口
    saved = client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={"drafts": [save_draft("今天的事")]},
    )
    assert saved.status_code == 200, saved.text

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "planRevision": 0,
        "suggestedTargetDate": None,
        "drafts": [],
        "rawCount": 0,
        "dropped": 0,
    }
    assert planner.calls == []
    assert len(_tasks(client, goal["id"])) == 1


def test_plan_only_fills_gap_dates(make_client):
    planner = MockGoalPlanner(
        tasks=[
            plan_task("做数学", TODAY),
            plan_task("已有任务日", TODAY + timedelta(days=1)),  # 已有任务 → 丢弃
            plan_task("背单词", TODAY + timedelta(days=2)),
            plan_task("窗口外", TODAY + timedelta(days=30)),
        ]
    )
    client = make_client(planner)
    goal = create_plan_goal(
        client,
        targetDate=(TODAY + timedelta(days=4)).isoformat(),
    )
    # 已有任务：计划从 18 号起，1 号位（19 号）已有
    client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={"drafts": [save_draft("已有任务", planned_date=TODAY + timedelta(days=1))]},
    )

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")
    assert response.status_code == 200, response.text
    body = response.json()
    drafts = body["drafts"]
    assert {draft["plannedDate"] for draft in drafts} == {
        TODAY.isoformat(),
        (TODAY + timedelta(days=2)).isoformat(),
    }
    # 期 3.3：丢弃条数可见（已有任务日 + 窗口外各 1 条）
    assert body["rawCount"] == 4
    assert body["dropped"] == 2
    # 已有任务日不出现在模型输入的空缺日里
    assert (TODAY + timedelta(days=1)).isoformat() not in planner.calls[0].gap_dates


def test_plan_respects_unavailable_dates(make_client):
    planner = MockGoalPlanner(
        tasks=[
            plan_task("不可用日任务", TODAY),
            plan_task("正常任务", TODAY + timedelta(days=1)),
        ]
    )
    client = make_client(planner)
    goal = create_plan_goal(client, targetDate=(TODAY + timedelta(days=3)).isoformat())

    response = client.post(
        f"/api/v1/goals/{goal['id']}/plan",
        json={"unavailableDates": [TODAY.isoformat()]},
    )
    assert response.status_code == 200, response.text
    drafts = response.json()["drafts"]
    assert [draft["plannedDate"] for draft in drafts] == [
        (TODAY + timedelta(days=1)).isoformat()
    ]
    assert TODAY.isoformat() not in planner.calls[0].gap_dates
    assert planner.calls[0].unavailable_dates == [TODAY.isoformat()]


def test_plan_revision_increments_each_successful_round(make_client):
    planner = MockGoalPlanner(tasks=[plan_task("做数学", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(client)

    first = client.post(f"/api/v1/goals/{goal['id']}/plan").json()
    second = client.post(f"/api/v1/goals/{goal['id']}/plan").json()

    assert first["planRevision"] == 1
    assert second["planRevision"] == 2
    detail = client.get(f"/api/v1/goals/{goal['id']}").json()
    assert detail["goal"]["planRevision"] == 2


def test_plan_caps_horizon_at_60_days(make_client):
    planner = MockGoalPlanner(tasks=[])
    client = make_client(planner)
    goal = create_plan_goal(
        client,
        startDate=TODAY.isoformat(),
        targetDate=(TODAY + timedelta(days=500)).isoformat(),
    )

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 200
    assert len(planner.calls[0].gap_dates) == 60
    assert planner.calls[0].gap_dates[0] == TODAY.isoformat()
    assert planner.calls[0].gap_dates[-1] == (
        TODAY + timedelta(days=59)
    ).isoformat()


def test_plan_rejects_habit_goal(make_client):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)

    response = client.post(f"/api/v1/goals/{habit['id']}/plan")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "goal_not_plan"


def test_plan_rejects_archived_goal_without_model_call(make_client):
    """期 3.4：归档目标 /plan → 409，不调模型、不写库、revision 不变。"""
    planner = MockGoalPlanner(tasks=[plan_task("不应出现", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(client)
    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 200
    before = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]
    assert before["status"] == "archived"

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "goal_not_active"
    assert planner.calls == []
    after = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]
    assert after["planRevision"] == before["planRevision"]
    assert after["updatedAt"] == before["updatedAt"]
    assert _tasks(client, goal["id"]) == []


def test_plan_rejects_done_goal_without_model_call(make_client):
    planner = MockGoalPlanner(tasks=[plan_task("不应出现", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(client)
    assert (
        client.patch(
            f"/api/v1/goals/{goal['id']}", json={"status": "done"}
        ).status_code
        == 200
    )

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "goal_not_active"
    assert planner.calls == []
    assert client.get(f"/api/v1/goals/{goal['id']}").json()["goal"][
        "planRevision"
    ] == 0


def test_archived_habit_plan_returns_409_before_kind_check(make_client):
    """归档状态优先于 kind 校验：归档 habit 的 /plan 也是 409 goal_not_active。"""
    planner = MockGoalPlanner()
    client = make_client(planner)
    habit = create_habit_goal(client)
    client.delete(f"/api/v1/goals/{habit['id']}")

    response = client.post(f"/api/v1/goals/{habit['id']}/plan")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "goal_not_active"
    assert planner.calls == []


def test_plan_missing_goal_is_404(make_client):
    client = make_client(MockGoalPlanner())
    response = client.post(
        "/api/v1/goals/99999999-9999-4999-8999-999999999999/plan"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "goal_not_found"


def test_plan_missing_credential_returns_503_without_writing(make_client):
    from app.modules.tasks.services.model_adapter import DeepSeekGoalPlanner

    planner = DeepSeekGoalPlanner(api_key="")  # 无凭据：明确报错，不访问网络
    client = make_client(planner)
    goal = create_plan_goal(client)
    before = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "model_unavailable"
    assert error["message"] == "模型服务暂不可用，请稍后重试。"
    after = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]
    assert after["planRevision"] == 0
    assert after["updatedAt"] == before["updatedAt"]
    assert _tasks(client, goal["id"]) == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ModelUnavailableError("x"), 503, "model_unavailable"),
        (ModelTimeoutError("x"), 504, "extraction_timeout"),
        (ModelOutputInvalidError("x"), 502, "model_output_invalid"),
    ],
)
def test_plan_model_failures_do_not_write(
    make_client, error: Exception, status: int, code: str
):
    planner = MockGoalPlanner(error=error)
    client = make_client(planner)
    goal = create_plan_goal(client)
    before = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    after = client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]
    assert after["planRevision"] == 0
    assert after["updatedAt"] == before["updatedAt"]
    assert _tasks(client, goal["id"]) == []


def test_plan_invalid_model_draft_does_not_write(make_client):
    planner = MockGoalPlanner(tasks=[{"title": "   "}])
    client = make_client(planner)
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/plan")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "plan_validation_failed"
    assert response.json()["error"]["details"]["fieldErrors"]
    assert client.get(f"/api/v1/goals/{goal['id']}").json()["goal"][
        "planRevision"
    ] == 0


def test_plan_rejects_invalid_body(make_client):
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)

    bad_date = client.post(
        f"/api/v1/goals/{goal['id']}/plan",
        json={"unavailableDates": ["2026-13-01"]},
    )
    assert bad_date.status_code == 422
    assert bad_date.json()["error"]["code"] == "plan_validation_failed"

    unknown = client.post(
        f"/api/v1/goals/{goal['id']}/plan", json={"foo": 1}
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "invalid_request"


# --------------------------------------------------------------------------- #
# POST /goals/{id}/tasks：确认后落库（幂等）
# --------------------------------------------------------------------------- #


def test_save_tasks_writes_goal_link_and_plan_revision(make_client):
    planner = MockGoalPlanner(
        tasks=[
            plan_task("做数学", TODAY, clock="09:00:00"),
            plan_task("背单词", TODAY + timedelta(days=1)),
        ]
    )
    client = make_client(planner)
    goal = create_plan_goal(client)
    plan = client.post(f"/api/v1/goals/{goal['id']}/plan").json()

    response = client.post(
        f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": plan["drafts"]}
    )

    assert response.status_code == 200, response.text
    tasks = response.json()["tasks"]
    assert [task["title"] for task in tasks] == ["做数学", "背单词"]
    for task in tasks:
        assert task["goalId"] == goal["id"]
        assert task["occurrenceOf"] is None
        assert task["planRevision"] == plan["planRevision"] == 1
        assert task["status"] == "open"
    # 来源为 manual（不新增 Source.kind）
    source = client.get(f"/api/v1/sources/{tasks[0]['sourceId']}")
    assert source.status_code == 200
    assert source.json()["source"]["kind"] == "manual"
    # goalId 过滤生效
    filtered = _tasks(client, goal["id"])
    assert {task["id"] for task in filtered} == {
        task["id"] for task in tasks
    }
    # 进度
    progress = client.get(f"/api/v1/goals/{goal['id']}").json()["progress"]
    assert progress == {"total": 2, "completed": 0, "overdue": 0}


def test_save_tasks_is_idempotent(make_client, tmp_path):
    planner = MockGoalPlanner(tasks=[plan_task("做数学", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(client)
    drafts = client.post(f"/api/v1/goals/{goal['id']}/plan").json()["drafts"]

    first = client.post(f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": drafts})
    second = client.post(
        f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": drafts}
    )

    assert first.status_code == second.status_code == 200
    assert [task["id"] for task in second.json()["tasks"]] == [
        task["id"] for task in first.json()["tasks"]
    ]
    assert len(_tasks(client, goal["id"])) == 1
    # 幂等重放不重复创建来源
    payload = json.loads(
        (tmp_path / "data" / "state.json").read_text(encoding="utf-8")
    )
    assert len(payload["sources"]) == 1
    # 重启后仍然只有一条
    fresh = make_client(planner)
    assert len(_tasks(fresh, goal["id"])) == 1


def test_save_tasks_uses_server_plan_revision(make_client):
    """期 3.4：planRevision 服务端权威，忽略客户端传值。"""
    planner = MockGoalPlanner(tasks=[plan_task("做数学", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(client)
    plan = client.post(f"/api/v1/goals/{goal['id']}/plan").json()

    response = client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={"drafts": plan["drafts"], "planRevision": 7},
    )

    assert response.status_code == 200, response.text
    assert response.json()["tasks"][0]["planRevision"] == plan["planRevision"] == 1


def test_save_tasks_uses_latest_server_plan_revision(make_client):
    """客户端传过期 revision 时，任务仍按服务端当前 goal.planRevision 打标。"""
    planner = MockGoalPlanner(tasks=[plan_task("做数学", TODAY)])
    client = make_client(planner)
    goal = create_plan_goal(client)
    first = client.post(f"/api/v1/goals/{goal['id']}/plan").json()
    second = client.post(f"/api/v1/goals/{goal['id']}/plan").json()
    assert first["planRevision"] == 1
    assert second["planRevision"] == 2

    response = client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={"drafts": first["drafts"], "planRevision": first["planRevision"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["tasks"][0]["planRevision"] == 2


def test_save_tasks_accepts_confirmation_chain_alias(make_client):
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)

    response = client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={
            "confirmedTasks": [
                {
                    "draftId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    "title": "手动确认一条",
                    "startTime": None,
                    "dueTime": {
                        "rawExpression": TODAY.isoformat(),
                        "precision": "date",
                        "resolvedValue": TODAY.isoformat(),
                        "status": "resolved",
                    },
                    "requirements": ["带书"],
                    "applicability": {"text": None, "status": "not_stated"},
                    "sourceExcerpt": None,
                    "reminder": {
                        "mode": "none",
                        "requestedAt": None,
                        "relativeTo": None,
                        "offsetMinutes": None,
                    },
                }
            ]
        },
    )

    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["draftId"] == "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    assert task["goalId"] == goal["id"]
    assert task["requirements"] == ["带书"]


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"planRevision": 1}, 422, "plan_validation_failed"),
        ({"drafts": []}, 422, "empty_drafts"),
        ({"drafts": [{"title": "   "}]}, 422, "plan_validation_failed"),
        ({"drafts": [{"title": "x", "plannedDate": "2026-13-01"}]}, 422, "plan_validation_failed"),
        ({"drafts": [{"title": "x", "unknownKey": 1}]}, 400, "invalid_request"),
        ({"foo": 1}, 400, "invalid_request"),
        ({"drafts": [], "confirmedTasks": []}, 400, "invalid_request"),
    ],
)
def test_save_tasks_invalid_payloads(make_client, payload, status, code):
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/tasks", json=payload)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_save_tasks_missing_goal_404(make_client):
    client = make_client(MockGoalPlanner())
    response = client.post(
        "/api/v1/goals/99999999-9999-4999-8999-999999999999/tasks",
        json={"drafts": [{"title": "x"}]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "goal_not_found"


# --------------------------------------------------------------------------- #
# POST /goals/{id}/occurrences：习惯实例（未来 14 天，按自然日幂等）
# --------------------------------------------------------------------------- #


def test_occurrences_idempotent_and_daily(make_client):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)

    first = client.post(f"/api/v1/goals/{habit['id']}/occurrences")
    second = client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    assert first.status_code == 200, first.text
    assert first.json() == {"created": 14}
    assert second.status_code == 200
    assert second.json() == {"created": 0}

    tasks = _tasks(client, habit["id"])
    assert len(tasks) == 14
    dates = set()
    for task in tasks:
        assert task["goalId"] == habit["id"]
        assert task["occurrenceOf"] == habit["id"]
        assert task["planRevision"] is None
        # 期 3.2：dueTime 用 recurrence.time 的具体时刻，startTime 恒为 null
        assert task["startTime"] is None
        due = task["dueTime"]
        assert due["precision"] == "datetime"
        assert due["status"] == "resolved"
        assert due["timeZone"] == "Asia/Shanghai"
        assert due["resolvedValue"] == f"{due['resolvedValue'][:10]}T07:00:00+08:00"
        # durationMinutes 只进执行要求文案
        assert task["requirements"] == ["约 30 分钟"]
        dates.add(due["resolvedValue"][:10])
    expected = {(TODAY + timedelta(days=offset)).isoformat() for offset in range(14)}
    assert dates == expected


def test_occurrences_without_time_uses_2000(make_client):
    """期 3.2：未配置 recurrence.time 时实例 dueTime 补 20:00 +08:00。"""
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(
        client,
        recurrence={
            "freq": "daily",
            "weekdays": [],
            "time": None,
            "durationMinutes": None,
        },
    )

    first = client.post(f"/api/v1/goals/{habit['id']}/occurrences")
    second = client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    assert first.status_code == 200, first.text
    assert first.json() == {"created": 14}
    assert second.json() == {"created": 0}  # 幂等行为不变

    tasks = _tasks(client, habit["id"])
    assert len(tasks) == 14
    for task in tasks:
        assert task["startTime"] is None
        assert task["dueTime"]["precision"] == "datetime"
        assert task["dueTime"]["resolvedValue"] == (
            f"{task['dueTime']['resolvedValue'][:10]}T20:00:00+08:00"
        )
        assert task["requirements"] == []


def test_occurrences_calendar_range_hit(make_client):
    """日历按 from/to 过滤（due 优先）能命中习惯实例。"""
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)
    client.post(f"/api/v1/goals/{habit['id']}/occurrences")
    target_day = TODAY + timedelta(days=3)

    response = client.get(
        "/api/v1/tasks",
        params={
            "status": "all",
            "from": target_day.isoformat(),
            "to": target_day.isoformat(),
        },
    )

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["goalId"] == habit["id"]
    assert tasks[0]["occurrenceOf"] == habit["id"]
    assert tasks[0]["dueTime"]["resolvedValue"] == (
        f"{target_day.isoformat()}T07:00:00+08:00"
    )


def test_occurrences_respect_start_date(make_client):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(
        client, startDate=(TODAY + timedelta(days=2)).isoformat()
    )

    response = client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    assert response.status_code == 200
    assert response.json() == {"created": 12}
    assert len(_tasks(client, habit["id"])) == 12


def test_occurrences_weekly_only_matching_weekdays(make_client):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(
        client,
        recurrence={
            "freq": "weekly",
            "weekdays": [1, 3],
            "time": "07:00",
            "durationMinutes": None,
        },
    )
    expected = {
        (TODAY + timedelta(days=offset)).isoformat()
        for offset in range(14)
        if (TODAY + timedelta(days=offset)).isoweekday() in (1, 3)
    }

    response = client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    assert response.status_code == 200, response.text
    assert response.json() == {"created": len(expected)}
    titles = {task["title"] for task in _tasks(client, habit["id"])}
    assert titles == {"晨跑"}


def test_occurrences_persist_and_stay_idempotent_across_restart(make_client):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)
    assert client.post(f"/api/v1/goals/{habit['id']}/occurrences").json() == {
        "created": 14
    }

    fresh = make_client(MockGoalPlanner())
    again = fresh.post(f"/api/v1/goals/{habit['id']}/occurrences")
    assert again.json() == {"created": 0}
    assert len(_tasks(fresh, habit["id"])) == 14


def test_occurrences_use_single_manual_source(make_client, tmp_path):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)
    client.post(f"/api/v1/goals/{habit['id']}/occurrences")
    client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    payload = json.loads(
        (tmp_path / "data" / "state.json").read_text(encoding="utf-8")
    )
    assert len(payload["sources"]) == 1
    only_source = next(iter(payload["sources"].values()))
    assert only_source["kind"] == "manual"
    assert only_source["originalText"] == "习惯：晨跑"
    assert len(payload["tasks"]) == 14


def test_occurrences_reject_archived_habit(make_client, tmp_path):
    """期 3.4：归档 habit /occurrences → 409，不生成实例、不写库。"""
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)
    assert client.delete(f"/api/v1/goals/{habit['id']}").status_code == 200

    response = client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "goal_not_active"
    assert _tasks(client, habit["id"]) == []
    payload = json.loads(
        (tmp_path / "data" / "state.json").read_text(encoding="utf-8")
    )
    assert payload["tasks"] == {}
    assert payload["sources"] == {}


def test_occurrences_reject_done_habit(make_client):
    client = make_client(MockGoalPlanner())
    habit = create_habit_goal(client)
    assert (
        client.patch(
            f"/api/v1/goals/{habit['id']}", json={"status": "done"}
        ).status_code
        == 200
    )

    response = client.post(f"/api/v1/goals/{habit['id']}/occurrences")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "goal_not_active"
    assert _tasks(client, habit["id"]) == []


def test_occurrences_rejects_plan_goal(make_client):
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)

    response = client.post(f"/api/v1/goals/{goal['id']}/occurrences")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "goal_not_habit"


def test_occurrences_missing_goal_404(make_client):
    client = make_client(MockGoalPlanner())
    response = client.post(
        "/api/v1/goals/99999999-9999-4999-8999-999999999999/occurrences"
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# 进度（期 5）与 goalId 过滤
# --------------------------------------------------------------------------- #


def test_goal_progress_counts_completed_and_overdue(make_client):
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)
    past = (TODAY - timedelta(days=2)).isoformat()
    drafts = [
        save_draft(
            "逾期任务",
            planned_date=TODAY - timedelta(days=2),
            due_time={
                "rawExpression": "前天",
                "precision": "datetime",
                "resolvedValue": f"{past}T10:00:00+08:00",
                "status": "resolved",
            },
        ),
        save_draft("已完成任务", planned_date=TODAY - timedelta(days=1)),
        save_draft("未来任务", planned_date=TODAY + timedelta(days=2)),
    ]
    saved = client.post(
        f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": drafts}
    ).json()["tasks"]
    assert len(saved) == 3
    # 完成其中一条（按 title 找 id）
    completed = next(item for item in saved if item["title"] == "已完成任务")
    patch = client.patch(
        f"/api/v1/tasks/{completed['id']}", json={"status": "completed"}
    )
    assert patch.status_code == 200

    progress = client.get(f"/api/v1/goals/{goal['id']}").json()["progress"]
    assert progress == {"total": 3, "completed": 1, "overdue": 1}


def test_goal_id_filter_excludes_unrelated_tasks(make_client):
    client = make_client(MockGoalPlanner())
    goal = create_plan_goal(client)
    client.post(
        f"/api/v1/goals/{goal['id']}/tasks",
        json={"drafts": [save_draft("计划任务")]},
    )
    manual = client.post("/api/v1/tasks", json={"title": "普通待办"}).json()["task"]

    filtered = _tasks(client, goal["id"])
    assert [task["title"] for task in filtered] == ["计划任务"]
    assert manual["id"] not in {task["id"] for task in filtered}
    # 普通任务 goalId 为 null
    detail = client.get(f"/api/v1/tasks/{manual['id']}").json()["task"]
    assert detail["goalId"] is None


def test_task_goal_fields_persisted_on_disk(make_client, tmp_path):
    client = make_client(MockGoalPlanner(tasks=[plan_task("做数学", TODAY)]))
    goal = create_plan_goal(client)
    drafts = client.post(f"/api/v1/goals/{goal['id']}/plan").json()["drafts"]
    client.post(f"/api/v1/goals/{goal['id']}/tasks", json={"drafts": drafts})

    payload = json.loads(
        (tmp_path / "data" / "state.json").read_text(encoding="utf-8")
    )
    stored = next(iter(payload["tasks"].values()))
    assert stored["goalId"] == goal["id"]
    assert stored["planRevision"] == 1
    assert stored["occurrenceOf"] is None
