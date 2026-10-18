"""TaskDraft, DraftSet, and Task entities on top of TaskFields and Reminder."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.modules.tasks.domain.fields import ReviewIssue, TaskFields, derive_review_issues
from app.modules.tasks.domain.primitives import (
    StrictModel,
    validate_optional_timestamp,
    validate_optional_uuid,
    validate_timestamp,
    validate_uuid,
)
from app.modules.tasks.domain.reminders import Reminder
from app.modules.tasks.domain.sources import SourceMetadata


Status = Literal["open", "completed"]
DraftSetStatus = Literal["review", "no_tasks"]


class TaskDraft(TaskFields):
    id: str
    source_id: str = Field(alias="sourceId")
    review_issues: list[ReviewIssue] = Field(alias="reviewIssues")
    reminder: Reminder

    @field_validator("id", "source_id")
    @classmethod
    def _check_uuids(cls, value: str, info) -> str:
        return validate_uuid(value, info.field_name)

    @model_validator(mode="after")
    def _finalize(self) -> "TaskDraft":
        if self.reminder.revision is not None:
            raise ValueError("TaskDraft reminder must keep revision null")
        if self.reminder.state not in ("not_set", "blocked", "scheduled"):
            raise ValueError(
                "TaskDraft reminder must use not_set/blocked/scheduled state"
            )
        self.reminder.scheduled_against(
            self.start_time, self.due_time, self.applicability
        )
        self.review_issues = derive_review_issues(self)
        return self


class DraftSet(StrictModel):
    draft_set_id: str = Field(alias="draftSetId")
    source: SourceMetadata
    status: DraftSetStatus
    drafts: list[TaskDraft]

    @field_validator("draft_set_id")
    @classmethod
    def _check_set_id(cls, value: str) -> str:
        return validate_uuid(value, "draftSetId")

    @model_validator(mode="after")
    def _validate_membership(self) -> "DraftSet":
        if self.status == "no_tasks":
            if self.drafts:
                raise ValueError("no_tasks DraftSet must have an empty drafts list")
        else:  # review
            if not self.drafts:
                raise ValueError("review DraftSet must contain at least one draft")
        ids = [draft.id for draft in self.drafts]
        if len(set(ids)) != len(ids):
            raise ValueError("DraftSet draft IDs must be unique within the batch")
        for draft in self.drafts:
            if draft.source_id != self.source.id:
                raise ValueError("draft sourceId must equal DraftSet source.id")
        return self


class Task(TaskFields):
    id: str
    draft_id: str = Field(alias="draftId")
    source_id: str = Field(alias="sourceId")
    # 期 3：长期任务关联（可选）。通知/手动任务这三项均为 null。
    goal_id: str | None = Field(default=None, alias="goalId")
    occurrence_of: str | None = Field(default=None, alias="occurrenceOf")
    plan_revision: int | None = Field(default=None, alias="planRevision")
    review_issues: list[ReviewIssue] = Field(alias="reviewIssues")
    status: Status
    reminder: Reminder
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")

    @field_validator("id", "draft_id", "source_id")
    @classmethod
    def _check_uuids(cls, value: str, info) -> str:
        return validate_uuid(value, info.field_name)

    @field_validator("goal_id", "occurrence_of")
    @classmethod
    def _check_optional_uuids(cls, value: str | None, info) -> str | None:
        return validate_optional_uuid(value, info.field_name)

    @field_validator("plan_revision")
    @classmethod
    def _check_plan_revision(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("planRevision must be a non-negative integer or null")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def _check_stamps(cls, value: str, info) -> str:
        return validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def _finalize(self) -> "Task":
        if self.reminder.revision is None:
            raise ValueError("Task reminder must declare a non-null revision")
        if self.status == "completed" and self.reminder.state in (
            "scheduled",
            "blocked",
        ):
            raise ValueError("completed Task must not keep scheduled/blocked reminder")
        if self.status == "open":
            # scheduled requires open with resolved times and confirmed applicability.
            self.reminder.scheduled_against(
                self.start_time, self.due_time, self.applicability
            )
        # Terminal states (acknowledged/expired/cancelled) keep history; the
        # task-level validator never recomputes relative plans.
        self.review_issues = derive_review_issues(self)
        return self
