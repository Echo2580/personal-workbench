"""构造样本测试 T04-B 草稿集与完整任务实体。

所有数据均为实体测试的构造样本，不代表真实提取或保存结果。
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.modules.tasks.domain import (
    DraftSet,
    Reminder,
    Task,
    TaskDraft,
    derive_review_issues,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
DRAFT_ID = "22222222-2222-4222-8222-222222222222"
OTHER_DRAFT_ID = "66666666-6666-4666-8666-666666666666"
TASK_ID = "33333333-3333-4333-8333-333333333333"
SET_ID = "44444444-4444-4444-8444-444444444444"
VERSION = "55555555-5555-4555-8555-555555555555"
STAMP = "2026-10-20T08:00:00+08:00"

SOURCE_META = {
    "id": SOURCE_ID,
    "kind": "text",
    "mimeType": "text/plain; charset=utf-8",
    "fileName": None,
    "messageDate": None,
    "importedAt": STAMP,
    "contentSha256": "a" * 64,
}

LATER_ACK = "2026-10-20T12:00:00+08:00"

FIELDS = {
    "title": "交报告",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "请交报告",
}

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

DRAFT = {
    **FIELDS,
    "id": DRAFT_ID,
    "sourceId": SOURCE_ID,
    "reviewIssues": [],
    "reminder": NONE,
}

SAVED = {
    **FIELDS,
    "id": TASK_ID,
    "draftId": DRAFT_ID,
    "sourceId": SOURCE_ID,
    "reviewIssues": [],
    "status": "open",
    "createdAt": STAMP,
    "updatedAt": STAMP,
    "reminder": {**NONE, "revision": VERSION},
}

DATETIME_DUE = {
    "rawExpression": "10月20日 10:00",
    "precision": "datetime",
    "resolvedValue": "2026-10-20T10:00:00+08:00",
    "timeZone": "Asia/Shanghai",
    "status": "resolved",
}

DATE_ONLY_DUE = {
    "rawExpression": "10月20日",
    "precision": "date",
    "resolvedValue": "2026-10-20",
    "timeZone": "Asia/Shanghai",
    "status": "resolved",
}

WAIT_DUE = {
    "rawExpression": "周五前",
    "precision": "relative",
    "resolvedValue": None,
    "timeZone": "Asia/Shanghai",
    "status": "needs_confirmation",
}

MANUAL_SCHEDULED = {
    "mode": "manual",
    "requestedAt": STAMP,
    "scheduledAt": STAMP,
    "relativeTo": None,
    "offsetMinutes": None,
    "state": "scheduled",
    "acknowledgedAt": None,
    "revision": None,
}

RELATIVE_SCHEDULED = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": "2026-10-20T09:30:00+08:00",
    "relativeTo": "due",
    "offsetMinutes": 30,
    "state": "scheduled",
    "acknowledgedAt": None,
    "revision": None,
}

RELATIVE_BLOCKED = {
    "mode": "relative",
    "requestedAt": None,
    "scheduledAt": None,
    "relativeTo": "due",
    "offsetMinutes": 30,
    "state": "blocked",
    "acknowledgedAt": None,
    "revision": VERSION,
}


def _saved(**overrides):
    payload = deepcopy(SAVED)
    for key, value in overrides.items():
        if value is _DELETE:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Delete:
    pass


_DELETE = _Delete()


def test_draft_set_membership():
    # no_tasks + 空数组。
    DraftSet.model_validate(
        {"draftSetId": SET_ID, "source": SOURCE_META, "status": "no_tasks", "drafts": []}
    )
    # review + 两个不同 draft ID、同 SOURCE_ID。
    other_draft = {**DRAFT, "id": OTHER_DRAFT_ID, "title": "另一个事项"}
    DraftSet.model_validate(
        {
            "draftSetId": SET_ID,
            "source": SOURCE_META,
            "status": "review",
            "drafts": [deepcopy(DRAFT), other_draft],
        }
    )

    invalid = [
        # 空 review。
        {"draftSetId": SET_ID, "source": SOURCE_META, "status": "review", "drafts": []},
        # 非空 no_tasks。
        {
            "draftSetId": SET_ID,
            "source": SOURCE_META,
            "status": "no_tasks",
            "drafts": [deepcopy(DRAFT)],
        },
        # 重复 draft ID。
        {
            "draftSetId": SET_ID,
            "source": SOURCE_META,
            "status": "review",
            "drafts": [deepcopy(DRAFT), deepcopy(DRAFT)],
        },
        # 另一个 sourceId。
        {
            "draftSetId": SET_ID,
            "source": SOURCE_META,
            "status": "review",
            "drafts": [{**DRAFT, "sourceId": TASK_ID}],
        },
        # 来源与草稿字段缺省/未知键。
        {"draftSetId": SET_ID, "source": SOURCE_META, "status": "no_tasks"},
        {
            "draftSetId": SET_ID,
            "source": {**SOURCE_META, "relativePath": None},
            "status": "no_tasks",
            "drafts": [],
        },
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            DraftSet.model_validate(payload)


def test_task_revision_context():
    assert TaskDraft.model_validate(deepcopy(DRAFT)).id == DRAFT_ID
    assert Task.model_validate(deepcopy(SAVED)).id == TASK_ID

    with pytest.raises(ValidationError):
        TaskDraft.model_validate({**DRAFT, "reminder": {**NONE, "revision": VERSION}})
    for terminal in ("acknowledged", "expired", "cancelled"):
        with pytest.raises(ValidationError):
            TaskDraft.model_validate(
                {
                    **DRAFT,
                    "reminder": {
                        **MANUAL_SCHEDULED,
                        "state": terminal,
                        "acknowledgedAt": LATER_ACK if terminal == "acknowledged" else None,
                    },
                }
            )
    # 已保存任务 revision=null（含 none）失败。
    with pytest.raises(ValidationError):
        Task.model_validate({**SAVED, "reminder": NONE})
    # Task 的 open/completed 可表达。
    assert Task.model_validate({**SAVED, "status": "completed"}).status == "completed"
    # completed + scheduled/blocked 失败。
    for reminder in (MANUAL_SCHEDULED, RELATIVE_SCHEDULED, RELATIVE_BLOCKED):
        with pytest.raises(ValidationError):
            Task.model_validate(
                {**SAVED, "status": "completed", "reminder": {**reminder, "revision": VERSION}}
            )
    # completed + none（非空版本）通过。
    Task.model_validate({**SAVED, "status": "completed"})
    # completed + 终态可保留。
    Task.model_validate(
        {
            **SAVED,
            "status": "completed",
            "reminder": {
                "mode": "relative",
                "requestedAt": None,
                "scheduledAt": "2026-10-20T09:30:00+08:00",
                "relativeTo": "due",
                "offsetMinutes": 30,
                "state": "cancelled",
                "acknowledgedAt": None,
                "revision": VERSION,
            },
        }
    )
    # 保留原五个公共导出。
    from app.modules.tasks.domain import (  # noqa: F401
        Applicability,
        ReviewIssue,
        TaskFields,
        TimeInfo,
    )


def test_scheduled_reminder_consistency():
    # 无日期任务 + 独立精确 manual scheduled 通过。
    manual_saved = {
        **MANUAL_SCHEDULED,
        "revision": VERSION,
    }
    Task.model_validate(_saved(reminder=manual_saved))
    TaskDraft.model_validate({**DRAFT, "reminder": MANUAL_SCHEDULED})

    # 时间待核对或条件待核对时 scheduled 失败；blocked 且 scheduledAt=null 保留配置。
    for wait_payload in (WAIT_DUE,):
        with pytest.raises(ValidationError):
            Task.model_validate(
                _saved(
                    dueTime=wait_payload,
                    reminder={**RELATIVE_SCHEDULED, "revision": VERSION},
                )
            )
        with pytest.raises(ValidationError):
            Task.model_validate(
                _saved(
                    dueTime=wait_payload,
                    reminder={**MANUAL_SCHEDULED, "revision": VERSION},
                )
            )
        Task.model_validate(
            _saved(
                dueTime=wait_payload,
                applicability={"text": "仅本班", "status": "confirmed"},
                reminder=RELATIVE_BLOCKED,
            )
        )
    with pytest.raises(ValidationError):
        Task.model_validate(
            _saved(
                applicability={"text": "仅本班", "status": "needs_confirmation"},
                reminder=MANUAL_SCHEDULED,
            )
        )
    Task.model_validate(
        _saved(
            applicability={"text": "仅本班", "status": "needs_confirmation"},
            reminder=RELATIVE_BLOCKED,
        )
    )

    # relative：基准 datetime，offset=30，09:30 通过、09:00 失败。
    Task.model_validate(
        _saved(dueTime=DATETIME_DUE, reminder={**RELATIVE_SCHEDULED, "revision": VERSION})
    )
    with pytest.raises(ValidationError):
        Task.model_validate(
            _saved(
                dueTime=DATETIME_DUE,
                reminder={
                    **RELATIVE_SCHEDULED,
                    "revision": VERSION,
                    "scheduledAt": "2026-10-20T09:00:00+08:00",
                },
            )
        )
    # 基准 date-only/null 不能 scheduled。
    with pytest.raises(ValidationError):
        Task.model_validate(
            _saved(
                dueTime=DATE_ONLY_DUE,
                reminder={**RELATIVE_SCHEDULED, "revision": VERSION},
            )
        )
    with pytest.raises(ValidationError):
        Task.model_validate(
            _saved(reminder={**RELATIVE_SCHEDULED, "revision": VERSION})
        )
    # 另一个时间待核对也不能 scheduled（startTime 待核对）。
    with pytest.raises(ValidationError):
        Task.model_validate(
            _saved(
                startTime=WAIT_DUE,
                dueTime=DATETIME_DUE,
                reminder={
                    **RELATIVE_SCHEDULED,
                    "revision": VERSION,
                    "relativeTo": "start",
                },
            )
        )
    # 基准是 start 的 datetime 计算正确。
    Task.model_validate(
        _saved(
            startTime={
                "rawExpression": "10月20日 09:00",
                "precision": "datetime",
                "resolvedValue": "2026-10-20T09:00:00+08:00",
                "timeZone": "Asia/Shanghai",
                "status": "resolved",
            },
            reminder={
                **RELATIVE_SCHEDULED,
                "revision": VERSION,
                "relativeTo": "start",
                "offsetMinutes": 30,
                "scheduledAt": "2026-10-20T08:30:00+08:00",
            },
        )
    )
    # scheduled 但任务 completed 已在上一测试覆盖；草稿 scheduled 按 open 语义允许。
    TaskDraft.model_validate({**DRAFT, "dueTime": DATETIME_DUE, "reminder": RELATIVE_SCHEDULED})


def test_terminal_reminder_history():
    reminder = {
        "mode": "relative",
        "requestedAt": None,
        "scheduledAt": "2026-10-20T09:30:00+08:00",
        "relativeTo": "due",
        "offsetMinutes": 30,
        "state": "acknowledged",
        "acknowledgedAt": LATER_ACK,
        "revision": VERSION,
    }
    base = _saved(dueTime=DATETIME_DUE, reminder=reminder)
    Task.model_validate(base)

    # 当前 dueTime 改为不同 datetime/date-only/null，终态字段保持。
    Task.model_validate(_saved(dueTime=DATE_ONLY_DUE, reminder=reminder))
    Task.model_validate(_saved(dueTime=None, reminder=reminder))
    Task.model_validate(
        _saved(
            dueTime={
                "rawExpression": "10月21日 10:00",
                "precision": "datetime",
                "resolvedValue": "2026-10-21T10:00:00+08:00",
                "timeZone": "Asia/Shanghai",
                "status": "resolved",
            },
            reminder=reminder,
        )
    )
    # 适用性后来待核对，也不抹去历史。
    Task.model_validate(
        _saved(
            applicability={"text": "仅本班", "status": "needs_confirmation"},
            reminder=reminder,
        )
    )

    expired = {**reminder, "state": "expired", "acknowledgedAt": None}
    Task.model_validate(_saved(dueTime=None, reminder=expired))
    cancelled = {**reminder, "state": "cancelled", "acknowledgedAt": None}
    Task.model_validate(_saved(dueTime=None, reminder=cancelled))

    # completed + cancelled 且从未有 scheduledAt 也通过。
    Task.model_validate(
        {
            **SAVED,
            "status": "completed",
            "reminder": {
                "mode": "relative",
                "requestedAt": None,
                "scheduledAt": None,
                "relativeTo": "due",
                "offsetMinutes": 30,
                "state": "cancelled",
                "acknowledgedAt": None,
                "revision": VERSION,
            },
        }
    )


def test_entity_review_issues():
    uncertain = {
        **FIELDS,
        "startTime": WAIT_DUE,
        "dueTime": WAIT_DUE,
        "applicability": {"text": "仅本班同学", "status": "needs_confirmation"},
        "sourceExcerpt": None,
    }
    draft_payload = {
        **uncertain,
        "id": DRAFT_ID,
        "sourceId": SOURCE_ID,
        "reviewIssues": [],
        "reminder": NONE,
    }
    saved_payload = {
        **uncertain,
        "id": TASK_ID,
        "draftId": DRAFT_ID,
        "sourceId": SOURCE_ID,
        "reviewIssues": [],
        "status": "open",
        "createdAt": STAMP,
        "updatedAt": STAMP,
        "reminder": {**NONE, "revision": VERSION},
    }

    for model, payload in ((TaskDraft, draft_payload), (Task, saved_payload)):
        entity = model.model_validate(deepcopy(payload))
        expected = derive_review_issues(entity)
        assert [(i.code, i.field) for i in entity.review_issues] == [
            ("time_needs_confirmation", "startTime"),
            ("time_needs_confirmation", "dueTime"),
            ("applicability_needs_confirmation", "applicability"),
            ("source_excerpt_missing", "sourceExcerpt"),
        ]
        assert entity.review_issues == expected

        # 修正后旧 issue 移除。
        corrected = deepcopy(payload)
        corrected["startTime"] = None
        corrected["dueTime"] = None
        corrected["applicability"] = {"text": None, "status": "not_stated"}
        corrected["sourceExcerpt"] = "请交报告"
        corrected["reviewIssues"] = [
            {
                "code": "source_excerpt_missing",
                "field": "sourceExcerpt",
                "message": "缺少可核对的原文片段。",
            }
        ]
        fixed = model.model_validate(corrected)
        assert fixed.review_issues == []
        assert fixed.model_dump(mode="json", by_alias=True)["reviewIssues"] == []

        # 原输入不被修改。
        assert payload["reviewIssues"] == []

        # 非法 issue 结构或代码仍失败。
        for issues in (
            [{"code": "unknown", "field": "sourceExcerpt", "message": "说明"}],
            [{"code": "source_excerpt_missing", "field": "applicability", "message": "说明"}],
            [{"code": "source_excerpt_missing", "field": "sourceExcerpt"}],
            [{"code": "source_excerpt_missing", "field": "sourceExcerpt", "message": "  "}],
            "not-a-list",
        ):
            broken = deepcopy(payload)
            broken["reviewIssues"] = issues
            with pytest.raises(ValidationError):
                model.model_validate(broken)


def _camel_to_snake(name: str) -> str:
    return "".join("_" + c.lower() if c.isupper() else c for c in name).lstrip("_")


def test_entity_required_keys_and_round_trip():
    # 原始五公共导出仍可导入。
    from app.modules.tasks.domain import (  # noqa: F401
        Applicability,
        ReviewIssue,
        TaskFields,
        TimeInfo,
        derive_review_issues as _derive,
    )

    draft_set_payload = {
        "draftSetId": SET_ID,
        "source": SOURCE_META,
        "status": "review",
        "drafts": [deepcopy(DRAFT)],
    }
    no_tasks_payload = {
        "draftSetId": SET_ID,
        "source": SOURCE_META,
        "status": "no_tasks",
        "drafts": [],
    }
    relative_saved = _saved(
        dueTime=DATETIME_DUE,
        reminder={**RELATIVE_SCHEDULED, "revision": VERSION},
    )

    valid = [
        (TaskDraft, deepcopy(DRAFT), "reviewIssues"),
        (TaskDraft, {**deepcopy(DRAFT), "dueTime": WAIT_DUE}, "reviewIssues"),
        (Task, deepcopy(SAVED), "reviewIssues"),
        (Task, deepcopy(relative_saved), "reviewIssues"),
        (DraftSet, draft_set_payload, "draftSetId"),
        (DraftSet, no_tasks_payload, "draftSetId"),
    ]

    for model, payload, snake_alias in valid:
        # 逐键删必填项失败（仅删顶层键；嵌套对象整体删除其键也覆盖）。
        for key in list(payload):
            broken = deepcopy(payload)
            del broken[key]
            with pytest.raises(ValidationError):
                model.model_validate(broken)

        # 未知键失败。
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "unknown": "value"})

        # 嵌套未知键失败。
        nested = deepcopy(payload)
        if "applicability" in nested:
            nested["applicability"]["extra"] = "value"
            with pytest.raises(ValidationError):
                model.model_validate(nested)
        if "reminder" in nested:
            broken_reminder = deepcopy(payload)
            broken_reminder["reminder"]["extra"] = "value"
            with pytest.raises(ValidationError):
                model.model_validate(broken_reminder)

        # snake_case 替代失败。
        snake = deepcopy(payload)
        value = snake.pop(snake_alias)
        snake[_camel_to_snake(snake_alias)] = value
        with pytest.raises(ValidationError):
            model.model_validate(snake)

        # 错误类型/非法 null：title 必填非空。
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "title": None})
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "title": 3})

        # JSON 往返：dump 后再 validate_json 不变（无丢 null、无身份/时间/原文变化、无多余派生字段）。
        obj = model.model_validate(deepcopy(payload))
        rebuilt = model.model_validate_json(obj.model_dump_json(by_alias=True))
        assert rebuilt.model_dump(mode="json", by_alias=True) == (
            obj.model_dump(mode="json", by_alias=True)
        )
