"""Reminder entity: eight required fields with strict mode/state combinations."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.modules.tasks.domain.primitives import (
    StrictModel,
    parse_timestamp,
    validate_optional_timestamp,
    validate_optional_uuid,
)


Mode = Literal["none", "manual", "relative"]
RelativeTo = Literal["start", "due"]
State = Literal[
    "not_set",
    "blocked",
    "scheduled",
    "acknowledged",
    "expired",
    "cancelled",
]


class Reminder(StrictModel):
    mode: Mode
    requested_at: str | None = Field(alias="requestedAt")
    scheduled_at: str | None = Field(alias="scheduledAt")
    relative_to: RelativeTo | None = Field(alias="relativeTo")
    offset_minutes: int | None = Field(alias="offsetMinutes")
    state: State
    acknowledged_at: str | None = Field(alias="acknowledgedAt")
    revision: str | None

    @field_validator("requested_at", "scheduled_at", "acknowledged_at")
    @classmethod
    def _check_timestamp(cls, value: str | None, info) -> str | None:
        return validate_optional_timestamp(value, info.field_name)

    @field_validator("revision")
    @classmethod
    def _check_revision(cls, value: str | None) -> str | None:
        return validate_optional_uuid(value, "revision")

    @field_validator("offset_minutes")
    @classmethod
    def _check_offset_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return None
        # Pydantic strict mode already rejects bool here, but be explicit so
        # the failure message stays inside the model.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("offsetMinutes must be a positive integer")
        if value <= 0:
            raise ValueError("offsetMinutes must be a positive integer")
        return value

    @model_validator(mode="after")
    def _check_combinations(self) -> "Reminder":
        if self.mode == "none":
            if (
                self.requested_at is not None
                or self.scheduled_at is not None
                or self.relative_to is not None
                or self.offset_minutes is not None
                or self.acknowledged_at is not None
            ):
                raise ValueError("none mode must leave time fields as null")
            if self.state != "not_set":
                raise ValueError("none mode must keep state not_set")
            return self

        # manual or relative: state must not be not_set
        if self.state == "not_set":
            raise ValueError("non-none mode must leave not_set only when blocked")

        if self.mode == "manual":
            if self.requested_at is None:
                raise ValueError("manual mode must declare requestedAt")
            if self.relative_to is not None or self.offset_minutes is not None:
                raise ValueError("manual mode must leave relative fields null")
        else:  # relative
            if self.requested_at is not None:
                raise ValueError("relative mode must leave requestedAt null")
            if self.relative_to is None:
                raise ValueError("relative mode must declare relativeTo")
            if self.offset_minutes is None:
                raise ValueError("relative mode must declare offsetMinutes")

        # scheduledAt nullity by state
        if self.state in ("not_set", "blocked") and self.scheduled_at is not None:
            raise ValueError("not_set/blocked reminder must have null scheduledAt")
        if self.state in ("scheduled", "acknowledged", "expired") and self.scheduled_at is None:
            raise ValueError(
                "scheduled/acknowledged/expired reminder must declare scheduledAt"
            )
        # cancelled: scheduledAt may be the last plan or null

        # acknowledgedAt iff acknowledged
        if self.state == "acknowledged" and self.acknowledged_at is None:
            raise ValueError("acknowledged reminder must declare acknowledgedAt")
        if self.state != "acknowledged" and self.acknowledged_at is not None:
            raise ValueError("only acknowledged reminder may have acknowledgedAt")

        # manual scheduledAt must equal requestedAt as the same moment
        if (
            self.mode == "manual"
            and self.scheduled_at is not None
            and self.requested_at is not None
        ):
            if parse_timestamp(self.scheduled_at) != parse_timestamp(self.requested_at):
                raise ValueError("manual scheduledAt must equal requestedAt")

        return self

    def scheduled_against(
        self,
        start_time,
        due_time,
        applicability,
    ) -> None:
        """Apply scheduled-only static checks (task-level). Raises ValueError."""
        if self.state != "scheduled":
            return
        if applicability is not None and applicability.status == "needs_confirmation":
            raise ValueError("scheduled reminder requires confirmed applicability")
        for label, info in (("startTime", start_time), ("dueTime", due_time)):
            if info is not None and info.status == "needs_confirmation":
                raise ValueError(
                    f"scheduled reminder requires resolved {label}"
                )

        if self.mode == "manual":
            # scheduledAt / requestedAt equality already enforced above.
            return

        # relative
        base = start_time if self.relative_to == "start" else due_time
        if (
            base is None
            or base.precision != "datetime"
            or base.status != "resolved"
            or base.resolved_value is None
        ):
            raise ValueError(
                "relative scheduled reminder requires a resolved datetime base"
            )
        base_dt = parse_timestamp(base.resolved_value)
        offset = self.offset_minutes or 0
        try:
            expected = base_dt - timedelta(minutes=offset)
        except OverflowError as exc:
            raise ValueError("relative offset overflows the time range") from exc
        if parse_timestamp(self.scheduled_at) != expected:
            raise ValueError(
                "relative scheduledAt must equal chosen base minus offsetMinutes"
            )
