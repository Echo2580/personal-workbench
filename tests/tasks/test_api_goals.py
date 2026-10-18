"""期 2 接口回归：/api/v1/goals CRUD 与 /api/v1/tasks 的 from/to/goalId 过滤。

错误信封与既有 API 一致：{"error": {code, message, details}}；未知/只读键
400、字段校验 422、实体不存在 404。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.modules.tasks.app_factory import create_tasks_app


STAMP = "2026-10-18T12:00:00+08:00"
GOAL_KEYS = {
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


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def client(data_root: Path) -> TestClient:
    return TestClient(create_tasks_app(data_root))


def plan_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "plan",
        "title": "考研复习",
        "startDate": "2026-10-20",
        "targetDate": "2027-06-30",
        "dailyCapacity": 3,
    }
    body.update(overrides)
    return body


def habit_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "habit",
        "title": "晨跑",
        "startDate": "2026-10-20",
        "recurrence": {
            "freq": "weekly",
            "weekdays": [1, 3, 5],
            "time": "07:00",
            "durationMinutes": 30,
        },
    }
    body.update(overrides)
    return body


def create_goal(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/v1/goals", json=body)
    assert response.status_code == 201, response.text
    return response.json()["goal"]


def create_task(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload = {"title": "事项", **overrides}
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["task"]


def time_date(value: str) -> dict[str, Any]:
    return {
        "rawExpression": value,
        "precision": "date",
        "resolvedValue": value,
        "status": "resolved",
    }


def time_datetime(value: str, clock: str = "18:00:00") -> dict[str, Any]:
    return {
        "rawExpression": value,
        "precision": "datetime",
        "resolvedValue": f"{value}T{clock}+08:00",
        "status": "resolved",
    }


def _titles(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {task["title"] for task in response.json()["tasks"]}


# --------------------------------------------------------------------------- #
# POST /goals
# --------------------------------------------------------------------------- #


def test_create_plan_goal_returns_201_with_full_entity(client: TestClient):
    response = client.post("/api/v1/goals", json=plan_body())

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"goal"}
    goal = body["goal"]
    assert set(goal) == GOAL_KEYS
    assert goal["kind"] == "plan"
    assert goal["title"] == "考研复习"
    assert goal["status"] == "active"
    assert goal["planRevision"] == 0
    assert goal["description"] is None
    assert goal["constraints"] is None
    assert goal["recurrence"] is None
    assert goal["startDate"] == "2026-10-20"
    assert goal["targetDate"] == "2027-06-30"
    assert goal["dailyCapacity"] == 3
    # id 为小写标准 UUID；时间戳使用 +08:00
    assert uuid.UUID(goal["id"])
    assert goal["id"] == goal["id"].lower()
    assert goal["createdAt"].endswith("+08:00")
    assert goal["updatedAt"] == goal["createdAt"]
    # 落盘后可再次列出
    listing = client.get("/api/v1/goals")
    assert [item["id"] for item in listing.json()["goals"]] == [goal["id"]]


def test_create_habit_goal_returns_recurrence(client: TestClient):
    goal = create_goal(client, habit_body(title="晨跑 5 公里"))

    assert goal["kind"] == "habit"
    assert goal["targetDate"] is None
    assert goal["dailyCapacity"] is None
    assert goal["recurrence"] == {
        "freq": "weekly",
        "weekdays": [1, 3, 5],
        "time": "07:00",
        "durationMinutes": 30,
    }

    detail = client.get(f"/api/v1/goals/{goal['id']}")
    assert detail.status_code == 200
    assert detail.json()["goal"] == goal


def test_created_goal_persists_across_restart(data_root: Path):
    first = TestClient(create_tasks_app(data_root))
    goal = create_goal(first, plan_body())

    second = TestClient(create_tasks_app(data_root))
    detail = second.get(f"/api/v1/goals/{goal['id']}")
    assert detail.status_code == 200
    assert detail.json()["goal"]["title"] == "考研复习"


def test_create_trims_title(client: TestClient):
    goal = create_goal(client, plan_body(title="  考研复习  "))
    assert goal["title"] == "考研复习"


def _missing(field: str) -> dict[str, Any]:
    body = plan_body()
    del body[field]
    return body


@pytest.mark.parametrize(
    "body",
    [
        _missing("targetDate"),  # plan 必填
        _missing("dailyCapacity"),  # plan 必填
        plan_body(recurrence={"freq": "daily", "weekdays": []}),  # plan 不得有 recurrence
        habit_body(targetDate="2026-11-01"),  # habit targetDate 必须 null
        {k: v for k, v in habit_body().items() if k != "recurrence"},  # habit 必填
        habit_body(
            recurrence={"freq": "daily", "weekdays": [1], "time": None, "durationMinutes": None}
        ),
        habit_body(
            recurrence={"freq": "weekly", "weekdays": [], "time": None, "durationMinutes": None}
        ),
        habit_body(
            recurrence={"freq": "weekly", "weekdays": [1, 1], "time": None, "durationMinutes": None}
        ),
        plan_body(
            recurrence={"freq": "daily", "weekdays": [], "time": "25:00", "durationMinutes": None}
        ),
        plan_body(dailyCapacity=6),
        plan_body(title="   "),
        plan_body(title="x" * 201),
        plan_body(startDate="2026-02-30"),
        # 期 3：plan 的 startDate ≤ targetDate
        plan_body(startDate="2026-10-20", targetDate="2026-10-19"),
    ],
)
def test_create_goal_validation_failures_are_422(
    client: TestClient, body: dict[str, Any]
):
    response = client.post("/api/v1/goals", json=body)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "goal_validation_failed"
    assert error["details"]["fieldErrors"]


def test_create_goal_empty_body_is_422(client: TestClient):
    response = client.post("/api/v1/goals", json={})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "goal_validation_failed"


@pytest.mark.parametrize(
    ("key", "value", "expected_code"),
    [
        ("priority", "高", "unknown_field"),
        ("status", "done", "read_only_field"),
        ("planRevision", 3, "read_only_field"),
        ("id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "read_only_field"),
        ("createdAt", STAMP, "read_only_field"),
        ("updatedAt", STAMP, "read_only_field"),
    ],
)
def test_create_goal_rejects_unknown_and_read_only_fields(
    client: TestClient, key: str, value: Any, expected_code: str
):
    response = client.post("/api/v1/goals", json=plan_body(**{key: value}))

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["fieldErrors"] == [
        {
            "field": key,
            "code": expected_code,
            "message": error["details"]["fieldErrors"][0]["message"],
        }
    ]


@pytest.mark.parametrize("payload", [[], "not-an-object", 3])
def test_create_goal_body_must_be_json_object(client: TestClient, payload: Any):
    response = client.post("/api/v1/goals", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_request"


# --------------------------------------------------------------------------- #
# GET /goals
# --------------------------------------------------------------------------- #


def test_list_goals_filters_by_status_and_kind(client: TestClient):
    plan_a = create_goal(client, plan_body(title="计划 A"))
    plan_b = create_goal(client, plan_body(title="计划 B"))
    habit = create_goal(client, habit_body(title="习惯 C"))
    assert (
        client.patch(f"/api/v1/goals/{plan_b['id']}", json={"status": "done"}).status_code
        == 200
    )
    assert client.delete(f"/api/v1/goals/{habit['id']}").status_code == 200

    def ids(**params: str) -> set[str]:
        response = client.get("/api/v1/goals", params=params)
        assert response.status_code == 200, response.text
        return {goal["id"] for goal in response.json()["goals"]}

    assert ids() == {plan_a["id"], plan_b["id"], habit["id"]}
    assert ids(status="all") == {plan_a["id"], plan_b["id"], habit["id"]}
    assert ids(status="active") == {plan_a["id"]}
    assert ids(status="done") == {plan_b["id"]}
    assert ids(status="archived") == {habit["id"]}
    assert ids(kind="plan") == {plan_a["id"], plan_b["id"]}
    assert ids(kind="habit") == {habit["id"]}
    assert ids(status="done", kind="plan") == {plan_b["id"]}
    assert ids(status="active", kind="habit") == set()


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"status": "open"}, "invalid_status"),
        ({"kind": "todo"}, "invalid_kind"),
    ],
)
def test_list_goals_rejects_invalid_filters(
    client: TestClient, params: dict[str, str], code: str
):
    response = client.get("/api/v1/goals", params=params)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"]["fieldErrors"]


def test_list_goals_orders_by_created_at_desc(client: TestClient):
    first = create_goal(client, plan_body(title="第一条"))
    second = create_goal(client, plan_body(title="第二条"))
    third = create_goal(client, plan_body(title="第三条"))

    listing = client.get("/api/v1/goals").json()["goals"]
    assert [goal["id"] for goal in listing] == [
        third["id"],
        second["id"],
        first["id"],
    ]


# --------------------------------------------------------------------------- #
# GET /goals/{id}
# --------------------------------------------------------------------------- #


def test_get_goal_detail_and_not_found(client: TestClient):
    goal = create_goal(client, plan_body())

    detail = client.get(f"/api/v1/goals/{goal['id']}")
    assert detail.status_code == 200
    assert detail.json()["goal"] == goal

    missing = client.get("/api/v1/goals/99999999-9999-4999-8999-999999999999")
    assert missing.status_code == 404
    error = missing.json()["error"]
    assert error["code"] == "goal_not_found"
    assert error["details"] == {}


# --------------------------------------------------------------------------- #
# PATCH /goals/{id}
# --------------------------------------------------------------------------- #


def test_patch_goal_partial_update_keeps_other_fields(client: TestClient):
    goal = create_goal(client, plan_body(description="原来的描述"))

    response = client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"title": "考研复习（调整）", "description": None},
    )

    assert response.status_code == 200, response.text
    patched = response.json()["goal"]
    assert patched["title"] == "考研复习（调整）"
    assert patched["description"] is None
    # 未提交字段保持原值
    assert patched["kind"] == "plan"
    assert patched["targetDate"] == "2027-06-30"
    assert patched["dailyCapacity"] == 3
    assert patched["startDate"] == "2026-10-20"
    assert patched["planRevision"] == 0
    # updatedAt 被刷新且仍是 +08:00
    assert patched["updatedAt"] >= goal["updatedAt"]
    assert patched["updatedAt"].endswith("+08:00")


def test_patch_goal_status_transitions(client: TestClient):
    goal = create_goal(client, plan_body())

    for status in ("done", "active", "archived"):
        response = client.patch(
            f"/api/v1/goals/{goal['id']}", json={"status": status}
        )
        assert response.status_code == 200, response.text
        assert response.json()["goal"]["status"] == status
        assert client.get(f"/api/v1/goals/{goal['id']}").json()["goal"]["status"] == status


def test_patch_plan_validates_mutual_exclusion(client: TestClient):
    goal = create_goal(client, plan_body())
    url = f"/api/v1/goals/{goal['id']}"

    assert client.patch(url, json={"targetDate": "2027-09-30"}).status_code == 200
    assert client.patch(url, json={"dailyCapacity": 5}).status_code == 200

    for body in (
        {"targetDate": None},
        {"dailyCapacity": None},
        {"recurrence": {"freq": "daily", "weekdays": []}},
        {"dailyCapacity": 6},
        {"targetDate": "2027-13-01"},
        # 期 3：PATCH 也不能把 targetDate 改到 startDate 之前
        {"targetDate": "2026-10-19"},
    ):
        response = client.patch(url, json=body)
        assert response.status_code == 422, (body, response.text)
        assert response.json()["error"]["code"] == "goal_validation_failed"


def test_patch_habit_validates_mutual_exclusion(client: TestClient):
    goal = create_goal(client, habit_body())
    url = f"/api/v1/goals/{goal['id']}"

    updated = client.patch(
        url,
        json={
            "recurrence": {
                "freq": "weekly",
                "weekdays": [2, 4],
                "time": "06:30",
                "durationMinutes": 45,
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["goal"]["recurrence"]["weekdays"] == [2, 4]

    for body in (
        {"recurrence": None},
        {"targetDate": "2026-11-01"},
        {"recurrence": {"freq": "weekly", "weekdays": []}},
    ):
        response = client.patch(url, json=body)
        assert response.status_code == 422, (body, response.text)


def test_patch_goal_rejects_read_only_unknown_and_null(client: TestClient):
    goal = create_goal(client, plan_body())
    url = f"/api/v1/goals/{goal['id']}"

    read_only = (
        {"kind": "habit"},
        {"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
        {"planRevision": 1},
        {"createdAt": STAMP},
        {"updatedAt": STAMP},
    )
    for body in read_only:
        response = client.patch(url, json=body)
        assert response.status_code == 400, (body, response.text)
        error = response.json()["error"]
        assert error["code"] == "invalid_request"
        assert error["details"]["fieldErrors"][0]["code"] == "read_only_field"

    unknown = client.patch(url, json={"priority": "高"})
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fieldErrors"][0]["code"] == "unknown_field"

    for key in ("title", "startDate", "status"):
        response = client.patch(url, json={key: None})
        assert response.status_code == 422, (key, response.text)
        error = response.json()["error"]
        assert error["code"] == "goal_validation_failed"
        assert error["details"]["fieldErrors"][0]["code"] == "null_not_allowed"


def test_patch_goal_not_found(client: TestClient):
    response = client.patch(
        "/api/v1/goals/99999999-9999-4999-8999-999999999999",
        json={"title": "不存在"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "goal_not_found"


def test_patch_goal_persists_across_restart(data_root: Path):
    first = TestClient(create_tasks_app(data_root))
    goal = create_goal(first, plan_body())
    patched = first.patch(
        f"/api/v1/goals/{goal['id']}", json={"title": "重启后的标题"}
    ).json()["goal"]

    second = TestClient(create_tasks_app(data_root))
    detail = second.get(f"/api/v1/goals/{goal['id']}")
    assert detail.status_code == 200
    assert detail.json()["goal"]["title"] == "重启后的标题"
    assert detail.json()["goal"]["updatedAt"] == patched["updatedAt"]


# --------------------------------------------------------------------------- #
# DELETE /goals/{id}：归档而非删除
# --------------------------------------------------------------------------- #


def test_delete_archives_goal_instead_of_removing(
    client: TestClient, data_root: Path
):
    goal = create_goal(client, plan_body())

    response = client.delete(f"/api/v1/goals/{goal['id']}")
    assert response.status_code == 200, response.text
    archived = response.json()["goal"]
    assert archived["status"] == "archived"
    assert archived["id"] == goal["id"]
    assert archived["updatedAt"] >= goal["updatedAt"]

    detail = client.get(f"/api/v1/goals/{goal['id']}")
    assert detail.status_code == 200
    assert detail.json()["goal"]["status"] == "archived"

    # 重复归档幂等
    again = client.delete(f"/api/v1/goals/{goal['id']}")
    assert again.status_code == 200
    assert again.json()["goal"]["status"] == "archived"

    # 数据仍在快照 goals 分区内
    payload = json.loads((data_root / "state.json").read_text(encoding="utf-8"))
    assert payload["goals"][goal["id"]]["status"] == "archived"

    listing = client.get("/api/v1/goals", params={"status": "archived"})
    assert goal["id"] in {item["id"] for item in listing.json()["goals"]}


def test_delete_goal_does_not_affect_tasks(client: TestClient):
    task = create_task(client, title="待办不受影响")
    goal = create_goal(client, plan_body())

    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 200

    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 200
    assert task["id"] in {
        item["id"] for item in client.get("/api/v1/tasks?status=all").json()["tasks"]
    }


def test_delete_goal_not_found(client: TestClient):
    response = client.delete(
        "/api/v1/goals/99999999-9999-4999-8999-999999999999"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "goal_not_found"


def test_archived_goal_can_be_restored_by_patch(client: TestClient):
    goal = create_goal(client, plan_body())
    client.delete(f"/api/v1/goals/{goal['id']}")

    restored = client.patch(
        f"/api/v1/goals/{goal['id']}", json={"status": "active"}
    )
    assert restored.status_code == 200
    assert restored.json()["goal"]["status"] == "active"


# --------------------------------------------------------------------------- #
# GET /tasks 的 from/to/goalId 过滤
# --------------------------------------------------------------------------- #


@pytest.fixture()
def seeded_tasks(client: TestClient) -> dict[str, dict[str, Any]]:
    tasks = {
        "A": create_task(client, title="A", dueTime=time_datetime("2026-10-20")),
        "B": create_task(client, title="B", dueTime=time_datetime("2026-10-22")),
        "C": create_task(client, title="C", startTime=time_date("2026-10-21")),
        "D": create_task(
            client,
            title="D",
            startTime=time_datetime("2026-10-20", "08:00:00"),
            dueTime=time_datetime("2026-10-25", "23:59:00"),
        ),
        "E": create_task(client, title="E"),
        "F": create_task(
            client,
            title="F",
            dueTime={
                "rawExpression": "某个时间",
                "precision": "unknown",
                "resolvedValue": None,
                "status": "needs_confirmation",
            },
        ),
    }
    assert {task["title"] for task in tasks.values()} == set("ABCDEF")
    return tasks


def test_task_date_filter_includes_boundaries(client: TestClient, seeded_tasks):
    response = client.get(
        "/api/v1/tasks",
        params={"status": "all", "from": "2026-10-20", "to": "2026-10-21"},
    )
    # A(due 10-20)、C(start 10-21)、D(start 10-20) 命中；B(10-22) 不命中
    assert _titles(response) == {"A", "C", "D"}

    assert _titles(
        client.get(
            "/api/v1/tasks", params={"status": "all", "from": "2026-10-20", "to": "2026-10-20"}
        )
    ) == {"A", "D"}

    assert _titles(
        client.get("/api/v1/tasks", params={"status": "all", "from": "2026-10-25", "to": "2026-10-25"})
    ) == {"D"}


def test_task_date_filter_open_ended(client: TestClient, seeded_tasks):
    # 只给 from：dueTime 或 startTime 任一 >= from
    assert _titles(
        client.get("/api/v1/tasks", params={"status": "all", "from": "2026-10-22"})
    ) == {"B", "D"}

    # 只给 to：任一 <= to
    assert _titles(
        client.get("/api/v1/tasks", params={"status": "all", "to": "2026-10-21"})
    ) == {"A", "C", "D"}

    # 区间之外（D 最晚 10-25）为空
    assert _titles(
        client.get("/api/v1/tasks", params={"status": "all", "from": "2026-10-26"})
    ) == set()


def test_task_date_filter_excludes_unresolved_times(client: TestClient, seeded_tasks):
    # E 没有时间；F 的 dueTime 待确认（resolvedValue=null）→ 都不参与日期过滤
    titles = _titles(
        client.get(
            "/api/v1/tasks",
            params={"status": "all", "from": "2026-10-18", "to": "2026-12-31"},
        )
    )
    assert titles == {"A", "B", "C", "D"}


def test_task_date_filter_respects_status(client: TestClient, seeded_tasks):
    client.patch(
        f"/api/v1/tasks/{seeded_tasks['A']['id']}", json={"status": "completed"}
    )

    # 默认 status=open 不含已完成
    assert _titles(
        client.get("/api/v1/tasks", params={"from": "2026-10-20", "to": "2026-10-20"})
    ) == {"D"}

    assert _titles(
        client.get(
            "/api/v1/tasks",
            params={"status": "completed", "from": "2026-10-20", "to": "2026-10-20"},
        )
    ) == {"A"}


def test_task_date_filter_rejects_invalid_params(client: TestClient, seeded_tasks):
    for params, expected_fields in (
        ({"from": "2026/10/20"}, {"from"}),
        ({"to": "2026-02-30"}, {"to"}),
        ({"from": "20261020"}, {"from"}),
        ({"from": "2026-10-22", "to": "2026-10-20"}, {"from"}),
        ({"from": "bad", "to": "worse"}, {"from", "to"}),
    ):
        response = client.get("/api/v1/tasks", params=params)
        assert response.status_code == 400, (params, response.text)
        error = response.json()["error"]
        assert error["code"] == "invalid_filter"
        assert {
            item["field"] for item in error["details"]["fieldErrors"]
        } == expected_fields


def test_task_goal_id_filter_accepts_valid_uuid(client: TestClient, seeded_tasks):
    goal_uuid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    response = client.get("/api/v1/tasks", params={"status": "all", "goalId": goal_uuid})

    assert response.status_code == 200, response.text
    assert response.json()["tasks"] == []


def test_task_goal_id_filter_rejects_malformed_uuid(
    client: TestClient, seeded_tasks
):
    response = client.get("/api/v1/tasks", params={"goalId": "not-a-uuid"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_filter"
    assert error["details"]["fieldErrors"][0]["field"] == "goalId"


def test_task_date_and_goal_filters_combine(client: TestClient, seeded_tasks):
    response = client.get(
        "/api/v1/tasks",
        params={
            "status": "all",
            "from": "2026-10-20",
            "to": "2026-10-31",
            "goalId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        },
    )
    assert response.status_code == 200
    assert response.json()["tasks"] == []
