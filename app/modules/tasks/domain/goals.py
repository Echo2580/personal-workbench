"""Goal（长期任务）实体：plan / habit 两种形态与严格字段互斥。

期 2 只定义实体与校验，不生成每日计划；``planRevision`` 预留给期 3 的计划
生成链路，本期创建固定为 0、PATCH 不修改。
"""

from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from app.modules.tasks.domain.primitives import (
    StrictModel,
    validate_optional_date,
    validate_timestamp,
    validate_uuid,
)


GoalKind = Literal["plan", "habit"]
GoalStatus = Literal["active", "done", "archived"]
RecurrenceFreq = Literal["daily", "weekly"]

TITLE_MAX_LENGTH: Final = 200
_TIME_OF_DAY_PATTERN: Final = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
_WEEKDAY_MIN: Final = 1
_WEEKDAY_MAX: Final = 7


def _validate_nonblank(value: str | None, field_name: str) -> str | None:
    if value is not None and not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    return value


def validate_time_of_day(value: str | None, field_name: str = "time") -> str | None:
    """HH:MM（24 小时制）格式校验；None 原样返回。"""
    if value is None:
        return None
    if not _TIME_OF_DAY_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must use HH:MM in 24-hour format")
    return value


class Recurrence(StrictModel):
    """习惯的重现规则：daily 必须空 weekdays；weekly 必须非空且去重。"""

    freq: RecurrenceFreq
    weekdays: list[int]
    time: str | None
    duration_minutes: int | None = Field(alias="durationMinutes", ge=1, le=600)

    @field_validator("weekdays")
    @classmethod
    def _check_weekday_range(cls, value: list[int]) -> list[int]:
        if any(day < _WEEKDAY_MIN or day > _WEEKDAY_MAX for day in value):
            raise ValueError("weekdays must be integers between 1 and 7")
        return value

    @field_validator("time")
    @classmethod
    def _check_time_of_day(cls, value: str | None) -> str | None:
        return validate_time_of_day(value)

    @model_validator(mode="after")
    def _check_freq_weekdays(self) -> "Recurrence":
        if self.freq == "daily":
            if self.weekdays:
                raise ValueError("daily recurrence must keep weekdays empty")
            return self
        if not self.weekdays:
            raise ValueError("weekly recurrence requires at least one weekday")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("weekly recurrence weekdays must be unique")
        return self


class Goal(StrictModel):
    id: str
    kind: GoalKind
    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    description: str | None
    start_date: str = Field(alias="startDate")
    target_date: str | None = Field(alias="targetDate")
    daily_capacity: int | None = Field(alias="dailyCapacity", ge=1, le=5)
    constraints: list[str] | None
    recurrence: Recurrence | None
    status: GoalStatus
    plan_revision: int = Field(alias="planRevision", ge=0)
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return validate_uuid(value, "id")

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str | None) -> str | None:
        return _validate_nonblank(value, "description")

    @field_validator("start_date", "target_date")
    @classmethod
    def _check_date(cls, value: str | None, info) -> str | None:
        return validate_optional_date(value, info.field_name)

    @field_validator("constraints")
    @classmethod
    def _check_constraints(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not item.strip() for item in value):
            raise ValueError("constraints cannot contain blank items")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def _check_stamps(cls, value: str, info) -> str:
        return validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "Goal":
        """plan 与 habit 的互斥字段：plan 用 targetDate/dailyCapacity，
        habit 用 recurrence；不属于本 kind 的字段必须为 null。"""
        if self.kind == "plan":
            if self.target_date is None:
                raise ValueError("plan Goal must declare targetDate")
            if self.daily_capacity is None:
                raise ValueError("plan Goal must declare dailyCapacity")
            if self.recurrence is not None:
                raise ValueError("plan Goal must not declare recurrence")
            # 起止日期必须形成有效区间（两者均已校验为真实 YYYY-MM-DD，
            # 可直接按 ISO 字符串比较）。
            if self.target_date < self.start_date:
                raise ValueError("plan Goal targetDate must not precede startDate")
            return self

        if self.target_date is not None:
            raise ValueError("habit Goal must keep targetDate null")
        if self.recurrence is None:
            raise ValueError("habit Goal must declare recurrence")
        return self
