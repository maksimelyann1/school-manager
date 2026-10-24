"""Strict MCP inputs, independent of the app's pinned Pydantic environment."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Upload(Inputs):
    path: str = Field(min_length=1)
    filename: str | None = None


class StoredFile(Inputs):
    storage: Literal["template", "auto", "import"]
    stored_filename: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    type: str = "application/octet-stream"


class TemplateChanges(Inputs):
    name: str | None = Field(default=None, min_length=1)
    text: str | None = None
    stickers: list[dict] | None = None
    keep_file_ids: list[int] | None = None


class GroupChanges(Inputs):
    name: str | None = Field(default=None, min_length=1)
    telegram_id: str | None = None
    lesson_time: str | None = None
    lesson_day: str | None = None
    category_id: int | None = Field(default=None, ge=1)


class ScheduledChanges(Inputs):
    message: str | None = None
    send_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    send_day: str | None = None
    repeat_count: int | None = Field(default=None, ge=0)


class ReportSettingsChanges(Inputs):
    google_ai_model: str | None = None
    prompt_template: str | None = None
    auto_reports_enabled: bool | None = None
    report_delay_minutes: int | None = Field(default=None, ge=0, le=240)
    report_notifications_enabled: bool | None = None
    report_notification_delay_minutes: int | None = Field(default=None, ge=0, le=240)
    absent_followup_enabled: bool | None = None
    absent_followup_schedule_mode: Literal["after_report", "before_next_lesson"] | None = None
    absent_followup_delay_minutes: int | None = Field(default=None, ge=0, le=10080)
    absent_followup_before_lesson_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    absent_followup_template: str | None = None
    no_absents_followup_template: str | None = None
    default_duration_minutes: int | None = Field(default=None, ge=30, le=360)
    test_mode: bool | None = None


class LessonChanges(Inputs):
    group_name: str | None = None
    telegram_group_id: int | None = Field(default=None, ge=1)
    day: str | None = None
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    course: str | None = None
    lesson_code: str | None = None
    lesson_count: str | None = None
    lesson_title: str | None = None
    lesson_topic_detail: str | None = None
    lesson_report_text: str | None = None
    topic: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    last_report_date: str | None = None
    absents: str | None = None
    row_order: int | None = None


class CourseLessonCreate(Inputs):
    lesson_count: int | None = Field(default=None, ge=1)
    lesson_code: str | None = None
    module: str | None = None
    lesson_title: str | None = None
    lesson_topic_detail: str | None = None
    lesson_report_text: str | None = None
    notes: str | None = None


class CourseLessonChanges(CourseLessonCreate):
    row_order: int | None = None


class PlannerOptions(Inputs):
    category: Literal["lesson", "substitution", "preparation", "event", "other"] | None = None
    parent_id: str | None = None
    group_id: int | None = Field(default=None, ge=1)
    google_enabled: bool = False
    google_calendar_id: int | None = Field(default=None, ge=1)
    location: str = Field(default="", max_length=1000)
    recurrence: list[str] = Field(default_factory=list, max_length=20)
    attendees: list[dict] = Field(default_factory=list, max_length=100)
    meet_requested: bool = False


class ItemChanges(Inputs):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    date: str | None = None
    time: str | None = None
    end_date: str | None = None
    end_time: str | None = None
    status: Literal["open", "done", "cancelled"] | None = None
    fold: Literal[0, 1] | None = None
    kind: Literal["task", "event"] | None = None
    category: Literal["lesson", "substitution", "preparation", "event", "other"] | None = None
    timezone: str | None = None
    parent_id: str | None = None
    group_id: int | None = Field(default=None, ge=1)
    google_enabled: bool | None = None
    google_calendar_id: int | None = Field(default=None, ge=1)
    location: str | None = Field(default=None, max_length=1000)
    recurrence: list[str] | None = Field(default=None, max_length=20)
    attendees: list[dict] | None = Field(default=None, max_length=100)
    meet_requested: bool | None = None


def values(model: Inputs) -> dict:
    return model.model_dump(exclude_unset=True, mode="json")
