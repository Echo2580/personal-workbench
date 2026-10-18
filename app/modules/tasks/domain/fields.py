"""Strict, in-memory field models shared by task domain operations."""

from datetime import date, datetime, timedelta
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator


TimePrecision = Literal["datetime", "date", "day_part", "relative", "unknown"]
TimeStatus = Literal["resolved", "needs_confirmation"]
ApplicabilityStatus = Literal["not_stated", "confirmed", "needs_confirmation"]
ReviewCode = Literal[
    "time_needs_confirmation",
    "applicability_needs_confirmation",
    "source_excerpt_missing",
]
ReviewField = Literal["startTime", "dueTime", "applicability", "sourceExcerpt"]

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DATETIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+08:00\Z"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _validate_nonblank(value: str | None, field_name: str) -> str | None:
    if value is not None and not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    return value


class TimeInfo(_StrictModel):
    raw_expression: StrictStr | None = Field(alias="rawExpression")
    precision: TimePrecision
    resolved_value: StrictStr | None = Field(alias="resolvedValue")
    time_zone: StrictStr = Field(alias="timeZone")
    status: TimeStatus

    @field_validator("raw_expression")
    @classmethod
    def raw_expression_must_not_be_blank(cls, value: str | None) -> str | None:
        return _validate_nonblank(value, "rawExpression")

    @field_validator("time_zone")
    @classmethod
    def use_shanghai_time_zone(cls, value: str) -> str:
        if value != "Asia/Shanghai":
            raise ValueError("timeZone must be Asia/Shanghai")
        return value

    @model_validator(mode="after")
    def validate_resolution(self) -> "TimeInfo":
        value = self.resolved_value
        if self.status == "needs_confirmation":
            if value is not None:
                raise ValueError("unconfirmed time must not have resolvedValue")
            return self

        if self.precision not in ("date", "datetime"):
            raise ValueError("resolved time precision must be date or datetime")
        if value is None:
            raise ValueError("resolved time must have resolvedValue")

        if self.precision == "date":
            if not _DATE_PATTERN.fullmatch(value):
                raise ValueError("date must use YYYY-MM-DD")
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("date must be a real calendar date") from exc
            return self

        if not _DATETIME_PATTERN.fullmatch(value):
            raise ValueError("datetime must include seconds and +08:00 offset")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("datetime must be a valid local date and time") from exc
        if parsed.utcoffset() != timedelta(hours=8):
            raise ValueError("datetime must use +08:00 offset")
        return self


class Applicability(_StrictModel):
    text: StrictStr | None
    status: ApplicabilityStatus

    @field_validator("text")
    @classmethod
    def applicability_text_must_not_be_blank(cls, value: str | None) -> str | None:
        return _validate_nonblank(value, "text")

    @model_validator(mode="after")
    def validate_status_and_text(self) -> "Applicability":
        if self.status == "not_stated" and self.text is not None:
            raise ValueError("not_stated applicability must have null text")
        if self.status != "not_stated" and self.text is None:
            raise ValueError("confirmed applicability must have text")
        return self


class ReviewIssue(_StrictModel):
    code: ReviewCode
    field: ReviewField
    message: StrictStr

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        return _validate_nonblank(value, "message")  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_code_field_pair(self) -> "ReviewIssue":
        allowed_fields = {
            "time_needs_confirmation": {"startTime", "dueTime"},
            "applicability_needs_confirmation": {"applicability"},
            "source_excerpt_missing": {"sourceExcerpt"},
        }
        if self.field not in allowed_fields[self.code]:
            raise ValueError("review issue code and field do not match")
        return self


class TaskFields(_StrictModel):
    title: StrictStr
    start_time: TimeInfo | None = Field(alias="startTime")
    due_time: TimeInfo | None = Field(alias="dueTime")
    requirements: list[StrictStr]
    applicability: Applicability
    source_excerpt: StrictStr | None = Field(alias="sourceExcerpt")

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        return _validate_nonblank(value, "title")  # type: ignore[return-value]

    @field_validator("requirements")
    @classmethod
    def requirements_must_not_contain_blanks(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("requirements cannot contain blank items")
        return value

    @field_validator("source_excerpt")
    @classmethod
    def source_excerpt_must_not_be_blank(cls, value: str | None) -> str | None:
        return _validate_nonblank(value, "sourceExcerpt")


def derive_review_issues(fields: TaskFields) -> list[ReviewIssue]:
    """Derive fresh review issues from the current public task fields."""
    issues: list[ReviewIssue] = []
    for field_name, time_info in (
        ("startTime", fields.start_time),
        ("dueTime", fields.due_time),
    ):
        if time_info is not None and time_info.status == "needs_confirmation":
            issues.append(
                ReviewIssue(
                    code="time_needs_confirmation",
                    field=field_name,
                    message="请确认时间后再继续。",
                )
            )

    if fields.applicability.status == "needs_confirmation":
        issues.append(
            ReviewIssue(
                code="applicability_needs_confirmation",
                field="applicability",
                message="请确认该条件是否适用于你。",
            )
        )
    if fields.source_excerpt is None:
        issues.append(
            ReviewIssue(
                code="source_excerpt_missing",
                field="sourceExcerpt",
                message="缺少可核对的原文片段。",
            )
        )
    return issues
