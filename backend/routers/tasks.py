from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import Group
from task_models import PlannerItem, PlannerReminder, PlannerCalendar, PlannerConnection, PlannerExternalLink
from services.planner.items import cancel_reminders, local_datetime, queue_sync, schedule_fields, serialize, serialize_many, update_reminders, utc_now, zone

from services.planner.routes import PlannerRoute
router = APIRouter(prefix="/tasks", tags=["Задачник"], route_class=PlannerRoute)


class TaskValues(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=20000)
    kind: Literal["task", "event"] = "task"
    category: Literal["lesson", "substitution", "preparation", "event", "other"] = "preparation"
    status: Literal["open", "done", "cancelled"] = "open"
    date: str | None = None
    time: str | None = None
    end_date: str | None = None
    end_time: str | None = None
    timezone: str = "Europe/Kyiv"
    fold: Literal[0, 1] | None = None
    parent_id: str | None = None
    group_id: int | None = None
    google_enabled: bool = False


class CreateTask(TaskValues):
    request_id: UUID = Field(default_factory=uuid4)


class EditTask(BaseModel):
    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    kind: Literal["task", "event"] | None = None
    category: Literal["lesson", "substitution", "preparation", "event", "other"] | None = None
    status: Literal["open", "done", "cancelled"] | None = None
    date: str | None = None
    time: str | None = None
    end_date: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    fold: Literal[0, 1] | None = None
    parent_id: str | None = None
    group_id: int | None = None
    google_enabled: bool | None = None


class Revision(BaseModel):
    revision: int = Field(ge=1)


def get_item(db, item_id, writable=False):
    item = db.get(PlannerItem, item_id)
    if item is None:
        raise HTTPException(404, "Задачу не знайдено")
    if writable and item.read_only:
        raise HTTPException(403, "Цей календар доступний лише для перегляду. Створіть пов’язану задачу підготовки")
    return item


def validated_values(db, data, item_id=None):
    for key in ("title", "description", "kind", "category", "status", "timezone", "google_enabled"):
        if data.get(key) is None:
            raise HTTPException(422, f"Поле {key} не може бути порожнім")
    if not data["title"].strip():
        raise HTTPException(422, "Вкажіть назву задачі")
    if data["kind"] == "event" and data["status"] == "done":
        raise HTTPException(422, "Виконання позначається для задачі. Подію можна скасувати")
    if data.get("group_id") and db.get(Group, data["group_id"]) is None:
        raise HTTPException(422, "Групу не знайдено")
    if data.get("parent_id"):
        parent = get_item(db, data["parent_id"])
        existing = db.get(PlannerItem, item_id) if item_id else None
        same_parent = existing and existing.parent_id == parent.id
        if parent.id == item_id or (not same_parent and (parent.kind != "event" or parent.deleted_at)):
            raise HTTPException(422, "Підготовку можна пов’язати з наявною подією")
    values = {key: data[key] for key in ("title", "description", "kind", "category", "status", "parent_id", "group_id", "google_enabled")}
    values["title"] = values["title"].strip()
    values.update(schedule_fields(data))
    if values["google_enabled"] and not values["start_date"]:
        raise HTTPException(422, "Для Google Календаря потрібна дата")
    return values


@router.get("")
def list_tasks(start: date | None = None, end: date | None = None,
               bucket: Literal["calendar", "undated", "overdue", "trash", "all"] = "calendar",
               q: str = Query(default="", max_length=240), category: str = "", source: str = "",
               completed: bool = False, timezone_name: str = "Europe/Kyiv",
               limit: int = Query(default=500, ge=1, le=1000), offset: int = Query(default=0, ge=0),
               db: Session = Depends(get_db)):
    tz = zone(timezone_name)
    from services.planner.google_sync import touch_activity
    touch_activity()
    query = db.query(PlannerItem)
    visible_ids = db.query(PlannerExternalLink.item_id).join(PlannerCalendar, PlannerCalendar.id == PlannerExternalLink.calendar_id).join(PlannerConnection, PlannerConnection.id == PlannerCalendar.connection_id).filter(PlannerCalendar.visible == 1, PlannerConnection.state.in_(['connected', 'reauth', 'error']))
    query = query.filter(or_(PlannerItem.source != 'google', PlannerItem.id.in_(visible_ids)))
    query = query.filter(PlannerItem.deleted_at.isnot(None) if bucket == "trash" else PlannerItem.deleted_at.is_(None))
    if bucket != "trash" and not completed:
        query = query.filter(PlannerItem.status == "open")
    if q.strip():
        query = query.filter(PlannerItem.title.contains(q.strip(), autoescape=True))
    if category:
        query = query.filter(PlannerItem.category == category)
    if source:
        query = query.filter(PlannerItem.source == source)
    if bucket == "calendar":
        start = start or datetime.now(tz).date().replace(day=1)
        end = end or start + timedelta(days=42)
        if end <= start or (end - start).days > 370:
            raise HTTPException(422, "Виберіть діапазон до одного року")
        utc_start = datetime.combine(start, time(), tzinfo=tz).astimezone(timezone.utc).isoformat()
        utc_end = datetime.combine(end, time(), tzinfo=tz).astimezone(timezone.utc).isoformat()
        query = query.filter(or_(
            and_(PlannerItem.start_at.is_(None), PlannerItem.start_date < end.isoformat(), PlannerItem.end_date > start.isoformat()),
            and_(PlannerItem.start_at < utc_end, PlannerItem.end_at > utc_start),
        ))
    elif bucket == "undated":
        query = query.filter(PlannerItem.start_date.is_(None))
    elif bucket == "overdue":
        now = utc_now()
        query = query.filter(PlannerItem.kind == "task", PlannerItem.status == "open", or_(
            and_(PlannerItem.start_at.isnot(None), PlannerItem.start_at < now),
            and_(PlannerItem.start_at.is_(None), PlannerItem.start_date < datetime.now(tz).date().isoformat()),
        ))
    total = query.count()
    items = query.order_by(PlannerItem.start_date, PlannerItem.start_at, PlannerItem.created_at).offset(offset).limit(limit).all()
    return {"items": serialize_many(items, db), "total": total, "has_more": total > offset + len(items)}


@router.post("", status_code=201)
def create_task(payload: CreateTask, db: Session = Depends(get_db)):
    item_id = payload.request_id.hex
    existing = db.get(PlannerItem, item_id)
    if existing:
        return serialize(existing, db)
    values = validated_values(db, payload.model_dump())
    now = utc_now()
    item = PlannerItem(id=item_id, **values, created_at=now, updated_at=now,
                       completed_at=now if values["status"] == "done" else None)
    db.add(item)
    try:
        db.flush()
        queue_sync(db, item)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(PlannerItem, item_id)
        if not existing:
            raise
        return serialize(existing, db)
    return serialize(item, db)


@router.get("/{item_id}")
def read_task(item_id: str, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    data = serialize(item, db)
    parent = db.get(PlannerItem, item.parent_id) if item.parent_id else None
    data['parent'] = serialize(parent) if parent else None
    data['preparations'] = serialize_many(db.query(PlannerItem).filter_by(parent_id=item.id, deleted_at=None).all(), db)
    return data


@router.patch("/{item_id}")
def edit_task(item_id: str, payload: EditTask, db: Session = Depends(get_db)):
    item = get_item(db, item_id, writable=True)
    if item.deleted_at:
        raise HTTPException(409, "Спочатку відновіть задачу з кошика")
    old_data = serialize(item)
    data = {**old_data, **payload.model_dump(exclude_unset=True, exclude={"revision"})}
    # A partial date change keeps the original duration, including overnight events.
    if "date" in payload.model_fields_set and "end_date" not in payload.model_fields_set and data.get("date") and old_data.get("date"):
        try:
            shift = date.fromisoformat(data["date"]) - date.fromisoformat(old_data["date"])
        except (ValueError, TypeError):
            raise HTTPException(422, "Перевірте дату")
        data["end_date"] = (date.fromisoformat(old_data["end_date"]) + shift).isoformat() if old_data.get("end_date") else data["date"]
    if not data.get("date"):
        data.update(time=None, end_date=None, end_time=None)
    values = validated_values(db, data, item_id)
    now = utc_now()
    values.update(updated_at=now, revision=payload.revision + 1,
                  completed_at=(item.completed_at or now) if values["status"] == "done" else None)
    changed = db.execute(update(PlannerItem).where(PlannerItem.id == item_id, PlannerItem.revision == payload.revision).values(**values))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Задача вже змінилася. Оновіть її перед збереженням")
    db.refresh(item)
    update_reminders(db, item, old_data)
    queue_sync(db, item)
    db.commit()
    return serialize(item, db)


def set_deleted(db, item_id, revision, deleted):
    item = get_item(db, item_id, writable=True)
    now = utc_now()
    changed = db.execute(update(PlannerItem).where(PlannerItem.id == item_id, PlannerItem.revision == revision).values(
        deleted_at=now if deleted else None, updated_at=now, revision=revision + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Задача вже змінилася. Оновіть список")
    db.refresh(item)
    if deleted:
        cancel_reminders(db, item)
    queue_sync(db, item)
    db.commit()
    return serialize(item, db)


@router.delete("/{item_id}")
def delete_task(item_id: str, revision: int = Query(ge=1), db: Session = Depends(get_db)):
    return set_deleted(db, item_id, revision, True)


@router.post("/{item_id}/restore")
def restore_task(item_id: str, payload: Revision, db: Session = Depends(get_db)):
    return set_deleted(db, item_id, payload.revision, False)


class ReminderRequest(BaseModel):
    revision: int = Field(ge=1)
    channel: Literal["system", "telegram"] = "system"
    date: str
    time: str
    fold: Literal[0, 1] | None = None


@router.post("/{item_id}/reminders")
def add_reminder(item_id: str, payload: ReminderRequest, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    if item.deleted_at or item.status != "open" or item.revision != payload.revision:
        raise HTTPException(409, "Оновіть задачу перед створенням нагадування")
    at = local_datetime(payload.date, payload.time, item.timezone, payload.fold)
    if at <= datetime.now(timezone.utc):
        raise HTTPException(422, "Виберіть майбутній час нагадування")
    previous = db.query(PlannerReminder).filter_by(item_id=item_id, channel=payload.channel,
                                                 remind_at=at.isoformat()).first()
    if not previous:
        previous = PlannerReminder(item_id=item_id, channel=payload.channel, remind_at=at.isoformat(),
                                   revision=item.revision, updated_at=utc_now())
        db.add(previous)
    elif previous.state in {'cancelled', 'missed', 'error'}:
        previous.state, previous.error, previous.next_attempt_at = 'pending', None, None
        previous.random_id, previous.scheduled_message_id, previous.attempts = None, None, 0
        previous.revision, previous.updated_at = item.revision, utc_now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return serialize(item, db)


@router.delete("/{item_id}/reminders/{reminder_id}")
def remove_reminder(item_id: str, reminder_id: str, db: Session = Depends(get_db)):
    reminder = db.get(PlannerReminder, reminder_id)
    if not reminder or reminder.item_id != item_id:
        raise HTTPException(404, "Нагадування не знайдено")
    reminder.state = "cancel_pending" if reminder.channel == "telegram" and (
        reminder.scheduled_message_id or reminder.random_id) else "cancelled"
    reminder.updated_at = utc_now()
    reminder.next_attempt_at = None
    db.commit()
    return serialize(get_item(db, item_id), db)
