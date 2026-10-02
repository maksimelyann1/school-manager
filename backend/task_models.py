"""Independent storage for the planner; existing lesson/report tables are untouched."""
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from database import Base


class PlannerItem(Base):
    __tablename__ = "planner_items"

    id = Column(String, primary_key=True, default=lambda: uuid4().hex)
    title = Column(String(240), nullable=False)
    description = Column(Text, nullable=False, default="")
    location = Column(Text, nullable=False, default="")
    recurrence = Column(Text, nullable=False, default="[]")
    attendees = Column(Text, nullable=False, default="[]")
    meet_requested = Column(Integer, nullable=False, default=0)
    conference_data = Column(Text, nullable=True)
    kind = Column(String, nullable=False, default="task")
    category = Column(String, nullable=False, default="preparation")
    color = Column(String(7), nullable=True)
    status = Column(String, nullable=False, default="open")
    start_date = Column(String, nullable=True, index=True)
    end_date = Column(String, nullable=True)
    start_at = Column(String, nullable=True, index=True)
    end_at = Column(String, nullable=True)
    timezone = Column(String, nullable=False, default="Europe/Kyiv")
    parent_id = Column(String, ForeignKey("planner_items.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    source = Column(String, nullable=False, default="local")
    read_only = Column(Integer, nullable=False, default=0)
    google_enabled = Column(Integer, nullable=False, default=0)
    google_connection_id = Column(String, ForeignKey('planner_connections.id'), nullable=True)
    google_calendar_id = Column(Integer, ForeignKey('planner_calendars.id'), nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    completed_at = Column(String, nullable=True)
    deleted_at = Column(String, nullable=True, index=True)
    __table_args__ = (Index("ix_planner_status_date", "status", "start_date"),)


class PlannerAttachment(Base):
    __tablename__ = "planner_attachments"

    id = Column(String, primary_key=True, default=lambda: uuid4().hex)
    item_id = Column(String, ForeignKey("planner_items.id"), nullable=False, index=True)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False, default="application/octet-stream")
    size = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False)


class PlannerConnection(Base):
    __tablename__ = "planner_connections"
    id = Column(String, primary_key=True)
    account_id = Column(String, nullable=False)
    email = Column(String, nullable=False, default="")
    state = Column(String, nullable=False, default="connected")
    last_error = Column(String, nullable=True)
    last_sync_at = Column(String, nullable=True)
    next_sync_at = Column(String, nullable=True)
    sync_attempts = Column(Integer, nullable=False, default=0)
    events_write = Column(Integer, nullable=False, default=0)


class PlannerCalendar(Base):
    __tablename__ = "planner_calendars"
    id = Column(Integer, primary_key=True)
    connection_id = Column(String, ForeignKey("planner_connections.id"), nullable=False)
    remote_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    managed = Column(Integer, nullable=False, default=0)
    access_role = Column(String, nullable=False, default='reader')
    writable = Column(Integer, nullable=False, default=0)
    visible = Column(Integer, nullable=False, default=0)
    sync_token = Column(Text, nullable=True)
    last_sync_at = Column(String, nullable=True)
    sync_window_start = Column(String, nullable=True)
    sync_format = Column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("connection_id", "remote_id"),)


class PlannerExternalLink(Base):
    __tablename__ = "planner_external_links"
    id = Column(Integer, primary_key=True)
    item_id = Column(String, ForeignKey("planner_items.id"), nullable=False, index=True)
    calendar_id = Column(Integer, ForeignKey("planner_calendars.id"), nullable=False)
    event_id = Column(String, nullable=False)
    etag = Column(String, nullable=True)
    snapshot = Column(Text, nullable=True)
    conflict = Column(Text, nullable=True)
    pending_snapshot = Column(Text, nullable=True)
    pending_revision = Column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("calendar_id", "event_id"),)


class PlannerSyncJob(Base):
    __tablename__ = "planner_sync_jobs"
    id = Column(Integer, primary_key=True)
    item_id = Column(String, ForeignKey("planner_items.id"), nullable=False, unique=True)
    connection_id = Column(String, ForeignKey("planner_connections.id"), nullable=True)
    revision = Column(Integer, nullable=False)
    state = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(String, nullable=True)
    error = Column(String, nullable=True)


class PlannerReminder(Base):
    __tablename__ = "planner_reminders"
    id = Column(String, primary_key=True, default=lambda: uuid4().hex)
    item_id = Column(String, ForeignKey("planner_items.id"), nullable=False, index=True)
    channel = Column(String, nullable=False)
    remind_at = Column(String, nullable=False, index=True)
    revision = Column(Integer, nullable=False, default=1)
    state = Column(String, nullable=False, default="pending")
    account_id = Column(String, nullable=True)
    scheduled_message_id = Column(Integer, nullable=True)
    random_id = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(String, nullable=True)
    error = Column(String, nullable=True)
    updated_at = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('item_id', 'channel', 'remind_at'),)
