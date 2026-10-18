"""期 3：Task 的 goalId / occurrenceOf / planRevision 可选字段领域测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.tasks.domain import Task


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
DRAFT_ID = "22222222-2222-4222-8222-222222222222"
TASK_ID = "33333333-3333-4333-8333-333333333333"
GOAL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_GOAL_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
VERSION = "55555555-5555-4555-8555-555555555555"
STAMP = "2026-10-18T12:00:00+08:00"

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

BASE_TASK = {
    "id": TASK_ID,
    "draftId": DRAFT_ID,
    "sourceId": SOURCE_ID,
    "title": "做数学",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "做数学",
    "reviewIssues": [],
    "status": "open",
    "reminder": NONE_REMINDER,
    "createdAt": STAMP,
    "updatedAt": STAMP,
}


def test_goal_fields_default_to_null_and_dump_aliases():
    task = Task.model_validate(dict(BASE_TASK))

    assert task.goal_id is None
    assert task.occurrence_of is None
    assert task.plan_revision is None

    dumped = task.model_dump(mode="json", by_alias=True)
    assert dumped["goalId"] is None
    assert dumped["occurrenceOf"] is None
    assert dumped["planRevision"] is None
    # 内部 snake_case 名不出现在对外载荷里
    assert "goal_id" not in dumped
    assert "occurrence_of" not in dumped


def test_goal_fields_accept_valid_values():
    task = Task.model_validate(
        {
            **BASE_TASK,
            "goalId": GOAL_ID,
            "occurrenceOf": GOAL_ID,
            "planRevision": 3,
        }
    )

    assert task.goal_id == GOAL_ID
    assert task.occurrence_of == GOAL_ID
    assert task.plan_revision == 3
    dumped = task.model_dump(mode="json", by_alias=True)
    assert dumped["goalId"] == GOAL_ID
    assert dumped["occurrenceOf"] == GOAL_ID
    assert dumped["planRevision"] == 3
    # JSON 往返保持
    assert Task.model_validate(dumped) == task


def test_plan_task_with_only_goal_id_keeps_occurrence_null():
    task = Task.model_validate({**BASE_TASK, "goalId": GOAL_ID, "planRevision": 0})
    assert task.goal_id == GOAL_ID
    assert task.occurrence_of is None
    assert task.plan_revision == 0


@pytest.mark.parametrize("value", ["not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"])
def test_goal_id_must_be_lowercase_uuid(value: str):
    with pytest.raises(ValidationError):
        Task.model_validate({**BASE_TASK, "goalId": value})
    with pytest.raises(ValidationError):
        Task.model_validate({**BASE_TASK, "occurrenceOf": value})


def test_goal_fields_reject_empty_strings():
    with pytest.raises(ValidationError):
        Task.model_validate({**BASE_TASK, "goalId": ""})


@pytest.mark.parametrize("value", [-1, "3", 1.5, True])
def test_plan_revision_must_be_non_negative_strict_int(value):
    with pytest.raises(ValidationError):
        Task.model_validate({**BASE_TASK, "planRevision": value})


def test_plan_revision_null_allowed():
    assert Task.model_validate({**BASE_TASK, "planRevision": None}).plan_revision is None


def test_task_keeps_goal_fields_after_reminder_update():
    task = Task.model_validate(
        {**BASE_TASK, "goalId": GOAL_ID, "planRevision": 2}
    )
    updated = Task.model_validate(
        {**task.model_dump(mode="json", by_alias=True), "title": "做数学（二）"}
    )
    assert updated.goal_id == GOAL_ID
    assert updated.plan_revision == 2
