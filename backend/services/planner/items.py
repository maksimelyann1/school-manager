from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json

from fastapi import HTTPException

from task_models import PlannerExternalLink, PlannerReminder, PlannerSyncJob, PlannerConnection, PlannerCalendar


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise HTTPException(422, "Невідомий часовий пояс")


def local_datetime(day, clock, tz_name, fold=None):
    try:
        naive = datetime.fromisoformat(f"{day}T{clock}")
        if naive.tzinfo is not None:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "Перевірте дату й час")
    tz = zone(tz_name)
    options = []
    for choice in (0, 1):
        local = naive.replace(tzinfo=tz, fold=choice)
        value = local.astimezone(timezone.utc)
        if value.astimezone(tz).replace(tzinfo=None) == naive and value not in options:
            options.append(value)
    if not options:
        raise HTTPException(422, "Цього часу не існує через переведення годинника. Виберіть інший час")
    if len(options) > 1 and fold is None:
        raise HTTPException(422, "Цей час повторюється при переведенні годинника. Виберіть перше або друге входження")
    return options[min(fold or 0, len(options) - 1)]


def schedule_fields(data):
    day, clock = data.get("date"), data.get("time")
    tz_name = data.get("timezone") or "Europe/Kyiv"
    zone(tz_name)
    if not day:
        if clock or data.get("kind") == "event":
            raise HTTPException(422, "Для події або часу потрібна дата")
        return dict(start_date=None, end_date=None, start_at=None, end_at=None, timezone=tz_name)
    try:
        start_day = date.fromisoformat(day)
        end_day = date.fromisoformat(data.get("end_date") or day)
    except (ValueError, TypeError):
        raise HTTPException(422, "Перевірте дату")
    if not clock:
        if end_day < start_day:
            raise HTTPException(422, "Завершення не може бути раніше початку")
        return dict(start_date=day, end_date=(end_day + timedelta(days=1)).isoformat(),
                    start_at=None, end_at=None, timezone=tz_name)
    start = local_datetime(day, clock, tz_name, data.get("fold"))
    end_clock = data.get("end_time")
    end = (local_datetime(end_day.isoformat(), end_clock, tz_name, data.get("fold"))
           if end_clock else start + timedelta(minutes=30))
    if end <= start:
        raise HTTPException(422, "Час завершення має бути пізніше початку")
    return dict(start_date=start.astimezone(zone(tz_name)).date().isoformat(),
                end_date=end.astimezone(zone(tz_name)).date().isoformat(),
                start_at=start.isoformat(), end_at=end.isoformat(), timezone=tz_name)


def serialize(item, db=None, related=None):
    local_start = datetime.fromisoformat(item.start_at).astimezone(zone(item.timezone)) if item.start_at else None
    local_end = datetime.fromisoformat(item.end_at).astimezone(zone(item.timezone)) if item.end_at else None
    data = {key: getattr(item, key) for key in (
        "id", "title", "description", "kind", "category", "status", "timezone", "parent_id", "group_id",
        "source", "revision", "created_at", "updated_at", "completed_at", "deleted_at",
    )}
    data.update(date=local_start.date().isoformat() if local_start else item.start_date,
                fold=local_start.fold if local_start else None,
                time=local_start.strftime("%H:%M") if local_start else None,
                end_date=local_end.date().isoformat() if local_end else
                    (date.fromisoformat(item.end_date) - timedelta(days=1)).isoformat() if item.end_date else None,
                end_time=local_end.strftime("%H:%M") if local_end else None,
                start=item.start_at or item.start_date, end=item.end_at or item.end_date,
                all_day=not bool(item.start_at), read_only=bool(item.read_only), google_enabled=bool(item.google_enabled))
    if db is not None or related is not None:
        job, link, reminders = related if related is not None else (
            db.query(PlannerSyncJob).filter_by(item_id=item.id).first(),
            db.query(PlannerExternalLink).filter_by(item_id=item.id).first(),
            db.query(PlannerReminder).filter_by(item_id=item.id).all())
        data["sync_state"] = "conflict" if link and link.conflict else job.state if job else "synced" if link else "local"
        data["sync_error"] = job.error if job else None
        data["reminders"] = [{"id": r.id, "channel": r.channel, "remind_at": r.remind_at,
                               "state": r.state, "error": r.error} for r in reminders]
    return data


def serialize_many(items, db):
    ids = [item.id for item in items]
    if not ids:
        return []
    jobs = {row.item_id: row for row in db.query(PlannerSyncJob).filter(PlannerSyncJob.item_id.in_(ids))}
    links = {row.item_id: row for row in db.query(PlannerExternalLink).filter(PlannerExternalLink.item_id.in_(ids))}
    reminders = {}
    for row in db.query(PlannerReminder).filter(PlannerReminder.item_id.in_(ids)):
        reminders.setdefault(row.item_id, []).append(row)
    return [serialize(item, related=(jobs.get(item.id), links.get(item.id), reminders.get(item.id, []))) for item in items]


def update_reminders(db, item, old):
    if item.status != "open" or (old.get('date') and not item.start_date):
        cancel_reminders(db, item)
        return
    before = old.get("start")
    after = item.start_at or item.start_date
    shift = timedelta(0)
    if before and after != before:
        if bool(old.get("time")) != bool(item.start_at):
            cancel_reminders(db, item)
            return
        shift = datetime.fromisoformat(after) - datetime.fromisoformat(before)
    rows = db.query(PlannerReminder).filter_by(item_id=item.id).order_by(
        PlannerReminder.remind_at.desc() if shift > timedelta(0) else PlannerReminder.remind_at).all()
    for r in rows:
        if r.state in {"sent", "cancelled", "cancel_pending", "missed", "elapsed"}:
            continue
        if not item.start_at and shift:
            local = datetime.fromisoformat(r.remind_at).astimezone(zone(item.timezone)) + shift
            r.remind_at = local.astimezone(timezone.utc).isoformat()
        else:
            r.remind_at = (datetime.fromisoformat(r.remind_at) + shift).isoformat()
        r.revision = item.revision
        r.state = 'uncertain' if r.state == 'uncertain' else 'pending'
        r.next_attempt_at, r.error = None, None
        if r.remind_at <= utc_now():
            r.state = 'cancel_pending' if r.channel == 'telegram' and (r.scheduled_message_id or r.random_id) else 'missed'
            r.error = 'Новий час нагадування вже минув'
        r.updated_at = utc_now()
        collision = db.query(PlannerReminder).filter(PlannerReminder.item_id == item.id, PlannerReminder.channel == r.channel,
            PlannerReminder.remind_at == r.remind_at, PlannerReminder.id != r.id).first()
        if collision:
            if collision.state in {'sent', 'cancelled', 'missed', 'elapsed'}:
                db.delete(collision)
                db.flush([collision])
            else:
                raise HTTPException(409, 'На новий час уже є інше нагадування. Спочатку скасуйте його')
        db.flush([r])


def queue_sync(db, item):
    link = db.query(PlannerExternalLink).filter_by(item_id=item.id).first()
    if link and item.deleted_at is None and link.snapshot and json.loads(link.snapshot).get('status') == 'cancelled' and not link.conflict:
        db.delete(link)
        db.flush()
        link = None
        item.source = 'local'
    if not item.google_enabled and not link:
        return
    job = db.query(PlannerSyncJob).filter_by(item_id=item.id).first()
    if job is None:
        job = PlannerSyncJob(item_id=item.id, revision=item.revision)
        calendar = db.get(PlannerCalendar, link.calendar_id) if link else None
        connection = db.query(PlannerConnection).filter(PlannerConnection.state.in_(['connected', 'reauth', 'error'])).first()
        job.connection_id = item.google_connection_id or (calendar.connection_id if calendar else connection.id if connection else None)
        item.google_connection_id = job.connection_id
        db.add(job)
    job.revision = item.revision
    job.state, job.attempts, job.error, job.next_attempt_at = "pending", 0, None, None
    if job.connection_id:
        connection = db.get(PlannerConnection, job.connection_id)
        if connection and connection.state == 'connected':
            connection.next_sync_at = None


def cancel_reminders(db, item):
    for reminder in db.query(PlannerReminder).filter_by(item_id=item.id).all():
        if reminder.state in {"sent", "cancelled"}:
            continue
        reminder.state = "cancel_pending" if reminder.channel == "telegram" and (
            reminder.scheduled_message_id or reminder.random_id) else "cancelled"
        reminder.updated_at = utc_now()
        reminder.next_attempt_at = None
