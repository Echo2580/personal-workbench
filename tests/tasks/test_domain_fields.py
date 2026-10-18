from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.modules.tasks.domain import (
    Applicability,
    ReviewIssue,
    TaskFields,
    TimeInfo,
    derive_review_issues,
)


BASE = {
    "title": "提交报告",
    "startTime": None,
    "dueTime": None,
    "requirements": [],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "请提交报告",
}

DATE = {
    "rawExpression": "10月20日",
    "precision": "date",
    "resolvedValue": "2026-10-20",
    "timeZone": "Asia/Shanghai",
    "status": "resolved",
}

WAIT = {
    "rawExpression": "周五前",
    "precision": "relative",
    "resolvedValue": None,
    "timeZone": "Asia/Shanghai",
    "status": "needs_confirmation",
}


def test_required_nulls_and_aliases():
    fields = TaskFields.model_validate(BASE)

    assert set(fields.model_dump(by_alias=True)) == set(BASE)
    assert fields.start_time is None
    assert fields.due_time is None

    with_null_excerpt = deepcopy(BASE)
    with_null_excerpt["sourceExcerpt"] = None
    dumped = TaskFields.model_validate(with_null_excerpt).model_dump(by_alias=True)
    assert "sourceExcerpt" in dumped
    assert dumped["sourceExcerpt"] is None

    required_payloads = [
        (TaskFields, BASE),
        (TimeInfo, DATE),
        (Applicability, {"text": None, "status": "not_stated"}),
        (
            ReviewIssue,
            {
                "code": "source_excerpt_missing",
                "field": "sourceExcerpt",
                "message": "请补充原文片段",
            },
        ),
    ]
    for model, payload in required_payloads:
        for key in payload:
            incomplete = deepcopy(payload)
            del incomplete[key]
            with pytest.raises(ValidationError):
                model.model_validate(incomplete)

    with pytest.raises(ValidationError):
        TaskFields.model_validate({**BASE, "unknown": "value"})
    wrong_alias = deepcopy(BASE)
    del wrong_alias["startTime"]
    wrong_alias["start_time"] = None
    with pytest.raises(ValidationError):
        TaskFields.model_validate(wrong_alias)
    with pytest.raises(ValidationError):
        TaskFields.model_validate({**BASE, "start_time": None})
    with pytest.raises(ValidationError):
        TaskFields.model_validate({**BASE, "title": "另一个标题", "start_time": None})


def test_time_precision_and_format():
    assert TimeInfo.model_validate(DATE).model_dump(mode="json", by_alias=True) == DATE

    for value in ("2026-10-20T09:00:00+08:00", "2026-10-20T09:00:00.123456+08:00"):
        payload = {**DATE, "precision": "datetime", "resolvedValue": value}
        assert TimeInfo.model_validate(payload).resolved_value == value

    invalid_payloads = [
        {**DATE, "resolvedValue": "2026-02-30"},
        {**DATE, "resolvedValue": "2026-2-3"},
        {**DATE, "resolvedValue": "2026-10-20T09:00:00+08:00"},
        {**DATE, "precision": "datetime", "resolvedValue": "2026-10-20"},
        {**DATE, "precision": "datetime", "resolvedValue": "2026-10-20T09:00:00"},
        {**DATE, "precision": "datetime", "resolvedValue": "2026-10-20T09:00:00Z"},
        {**DATE, "precision": "datetime", "resolvedValue": "2026-10-20T09:00:00+00:00"},
        {**DATE, "timeZone": "UTC"},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            TimeInfo.model_validate(payload)


def test_time_status_combinations():
    assert TimeInfo.model_validate(WAIT).raw_expression == "周五前"

    invalid_payloads = [
        {**WAIT, "resolvedValue": "2026-10-20"},
        {**DATE, "resolvedValue": None},
        {
            **WAIT,
            "status": "resolved",
            "resolvedValue": "2026-10-20",
        },
        {
            **WAIT,
            "precision": "day_part",
            "status": "resolved",
            "resolvedValue": "2026-10-20",
        },
        {
            **WAIT,
            "precision": "unknown",
            "status": "resolved",
            "resolvedValue": "2026-10-20",
        },
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            TimeInfo.model_validate(payload)

    assert TimeInfo.model_validate({**WAIT, "rawExpression": None}).raw_expression is None
    with pytest.raises(ValidationError):
        TimeInfo.model_validate({**WAIT, "rawExpression": "  "})


def test_start_and_due_are_independent():
    start = {
        **DATE,
        "precision": "datetime",
        "resolvedValue": "2026-10-20T09:00:00+08:00",
    }
    due = {
        **DATE,
        "precision": "datetime",
        "resolvedValue": "2026-10-20T22:00:00+08:00",
    }
    payload = {**BASE, "startTime": start, "dueTime": due}
    fields = TaskFields.model_validate(payload)

    dumped = fields.model_dump(mode="json", by_alias=True)
    assert dumped["startTime"] == start
    assert dumped["dueTime"] == due

    only_start = TaskFields.model_validate({**payload, "dueTime": None})
    assert only_start.start_time is not None
    assert only_start.due_time is None
    only_due = TaskFields.model_validate({**payload, "startTime": None})
    assert only_due.start_time is None
    assert only_due.due_time is not None


def test_applicability_combinations():
    valid = [
        {"text": None, "status": "not_stated"},
        {"text": "仅本班同学", "status": "needs_confirmation"},
        {"text": "仅本班同学", "status": "confirmed"},
    ]
    for payload in valid:
        applicability = Applicability.model_validate(payload)
        assert applicability.model_dump(mode="json", by_alias=True) == payload

    invalid = [
        {"text": "条件", "status": "not_stated"},
        {"text": None, "status": "needs_confirmation"},
        {"text": " ", "status": "confirmed"},
        {"text": "条件", "status": "unknown"},
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            Applicability.model_validate(payload)


def test_strict_types_and_text():
    fields = TaskFields.model_validate({**BASE, "title": "  提交报告  "})
    assert fields.title == "提交报告"

    for title in (3, True, None, " \t "):
        with pytest.raises(ValidationError):
            TaskFields.model_validate({**BASE, "title": title})

    for requirements in ("要求", [None], [1], ["  "]):
        with pytest.raises(ValidationError):
            TaskFields.model_validate({**BASE, "requirements": requirements})
    assert TaskFields.model_validate(BASE).requirements == []

    with pytest.raises(ValidationError):
        TaskFields.model_validate({**BASE, "sourceExcerpt": "  "})
    assert TaskFields.model_validate({**BASE, "sourceExcerpt": None}).source_excerpt is None

    preserved = TaskFields.model_validate(
        {
            **BASE,
            "requirements": ["  图书馆提交  "],
            "sourceExcerpt": "  请于周五前提交  ",
        }
    )
    assert preserved.requirements == ["  图书馆提交  "]
    assert preserved.source_excerpt == "  请于周五前提交  "

    invalid_nested = deepcopy(BASE)
    invalid_nested["applicability"]["extra"] = "value"
    with pytest.raises(ValidationError):
        TaskFields.model_validate(invalid_nested)


def test_review_issue_pairs():
    valid = [
        {"code": "time_needs_confirmation", "field": "startTime", "message": "请确认开始时间"},
        {"code": "applicability_needs_confirmation", "field": "applicability", "message": "请确认适用条件"},
        {"code": "source_excerpt_missing", "field": "sourceExcerpt", "message": "请补充原文片段"},
    ]
    for payload in valid:
        assert ReviewIssue.model_validate(payload).model_dump(mode="json", by_alias=True) == payload

    invalid = [
        {"code": "time_needs_confirmation", "field": "applicability", "message": "时间"},
        {"code": "applicability_needs_confirmation", "field": "dueTime", "message": "条件"},
        {"code": "unknown", "field": "sourceExcerpt", "message": "说明"},
        {"code": "source_excerpt_missing", "field": "unknown", "message": "说明"},
        {"code": "source_excerpt_missing", "field": "sourceExcerpt", "message": "  "},
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            ReviewIssue.model_validate(payload)


def test_issue_derivation_and_rebuild():
    fields = TaskFields.model_validate(BASE)
    original_dump = fields.model_dump(mode="json", by_alias=True)
    original_payload = deepcopy(BASE)
    assert derive_review_issues(fields) == []

    uncertain = {
        **BASE,
        "startTime": WAIT,
        "dueTime": WAIT,
        "applicability": {"text": "仅本班同学", "status": "needs_confirmation"},
        "sourceExcerpt": None,
    }
    unresolved = TaskFields.model_validate(uncertain)
    issues = derive_review_issues(unresolved)
    assert [(issue.code, issue.field) for issue in issues] == [
        ("time_needs_confirmation", "startTime"),
        ("time_needs_confirmation", "dueTime"),
        ("applicability_needs_confirmation", "applicability"),
        ("source_excerpt_missing", "sourceExcerpt"),
    ]
    assert all(issue.message.strip() for issue in issues)
    assert unresolved.model_dump(mode="json", by_alias=True) == uncertain
    assert uncertain == {
        **BASE,
        "startTime": WAIT,
        "dueTime": WAIT,
        "applicability": {"text": "仅本班同学", "status": "needs_confirmation"},
        "sourceExcerpt": None,
    }
    assert len(derive_review_issues(unresolved)) == 4

    corrected = deepcopy(uncertain)
    corrected["startTime"] = DATE
    corrected["dueTime"] = None
    corrected["applicability"] = {"text": "仅本班同学", "status": "confirmed"}
    corrected["sourceExcerpt"] = "周五前提交报告"
    assert derive_review_issues(TaskFields.model_validate(corrected)) == []
    assert fields.model_dump(mode="json", by_alias=True) == original_dump
    assert BASE == original_payload


def test_json_round_trip():
    payload = {**BASE, "dueTime": WAIT, "requirements": ["提交 PDF"]}
    first = TaskFields.model_validate(payload)
    dumped = first.model_dump_json(by_alias=True)
    rebuilt = TaskFields.model_validate_json(dumped)

    assert rebuilt.model_dump(mode="json", by_alias=True) == first.model_dump(
        mode="json", by_alias=True
    )
    assert set(rebuilt.model_dump(mode="json", by_alias=True)) == set(BASE)
    assert "due_time" not in dumped
