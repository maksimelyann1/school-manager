"""Read-only report evidence for local assistants; never sends or reconciles reports."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
import sys

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import ParentReportLesson, ParentReportRun, ParentReportSettings
from report_delivery import is_ambiguous_error
from routers.parents_report import (
    KYIV_TZ, WEEKDAY_MAP, _normalize_day, _normalize_time, _parse_iso_datetime,
    _parse_report_date, DEFAULT_DURATION_MINUTES,
)

router = APIRouter(prefix="/assistant", tags=["Локальний асистент"])


@router.get("/courses/{course_id}")
def read_course(course_id: int, db: Session = Depends(get_db)):
    from models import ParentReportCourse
    from routers.parents_report import _serialize_course
    course = db.get(ParentReportCourse, course_id)
    if course is None:
        raise HTTPException(404, "Курс не знайдено")
    return _serialize_course(course, include_lessons=True)


@router.get("/status")
def assistant_status():
    from version_config import APP_VERSION
    return {"service": "school_manager", "version": APP_VERSION, "assistant_api": 1,
            "runtime": "installed" if getattr(sys, "frozen", False) else "source",
            "capabilities": ["tasks", "events", "system_reminders", "report_audit"]}


def _run_data(run):
    return {"id": run.id, "status": run.status, "error": run.error or "",
            "telegram_message_id": run.telegram_message_id, "created_at": run.created_at}


@router.get("/reports")
def check_reports(start: date | None = None, end: date | None = None,
                  group: str = "", db: Session = Depends(get_db)):
    now = datetime.now(KYIV_TZ)
    end = end or now.date()
    start = start or end - timedelta(days=6)
    if end < start or (end - start).days > 30:
        raise HTTPException(422, "Виберіть період до 31 дня включно")
    settings = db.query(ParentReportSettings).first()
    duration_default = (settings.default_duration_minutes if settings else None) or DEFAULT_DURATION_MINUTES
    delay = max(0, (settings.report_delay_minutes or 0) if settings else 0)
    lessons = db.query(ParentReportLesson).order_by(ParentReportLesson.id).all()
    runs = db.query(ParentReportRun).filter(
        ParentReportRun.lesson_date >= start.isoformat(),
        ParentReportRun.lesson_date <= end.isoformat(), ParentReportRun.is_test == 0,
    ).order_by(ParentReportRun.id).all()
    by_id, legacy = defaultdict(list), defaultdict(list)
    for run in runs:
        (by_id[run.lesson_id, run.lesson_date] if run.lesson_id is not None else
         legacy[run.lesson_group_name, run.lesson_date]).append(run)
    expected, excluded, invalid = {}, [], []
    needle = group.strip().casefold()
    name_counts = Counter(lesson.group_name for lesson in lessons)
    for lesson in lessons:
        if needle and needle not in lesson.group_name.casefold():
            continue
        if lesson.is_paused:
            excluded.append({"lesson_id": lesson.id, "group": lesson.group_name, "reason": "paused"})
            continue
        duration = lesson.duration_minutes or duration_default
        postponed = _parse_iso_datetime(lesson.postponed_start_at)
        dates = []
        if postponed:
            dates = [postponed]
        else:
            weekday = WEEKDAY_MAP.get(_normalize_day(lesson.day or ""))
            clock = _normalize_time(lesson.start_time or "")
            try:
                if weekday is None:
                    raise ValueError()
                hour, minute = map(int, clock.split(":"))
                day = start + timedelta(days=(weekday - start.weekday()) % 7)
                while day <= end:
                    dates.append(datetime(day.year, day.month, day.day, hour, minute, tzinfo=KYIV_TZ))
                    day += timedelta(days=7)
            except (ValueError, TypeError):
                invalid.append({"lesson_id": lesson.id, "group": lesson.group_name, "reason": "invalid_schedule"})
                continue
        for at in dates:
            if not start <= at.date() <= end:
                continue
            key = (lesson.id, at.date().isoformat())
            evidence = by_id[key] + (legacy[lesson.group_name, key[1]] if name_counts[lesson.group_name] == 1 else [])
            expected[key] = {"lesson_id": lesson.id, "group": lesson.group_name,
                "lesson_date": key[1], "start": at.isoformat(),
                "available_at": (at + timedelta(minutes=duration + delay)).isoformat(),
                "schedule_source": "postponed" if postponed else "current_schedule",
                "marked_reported": bool((_parse_report_date(lesson.last_report_date or "") or date.min) >= at.date()),
                "runs": evidence}
    # Historical runs remain visible when a row has moved, been paused or deleted.
    used = {run.id for item in expected.values() for run in item["runs"]}
    for run in runs:
        if run.id in used or (needle and needle not in run.lesson_group_name.casefold()):
            continue
        key = ((run.lesson_id, run.lesson_date) if run.lesson_id is not None else
               (None, run.lesson_date, run.lesson_group_name))
        if key not in expected:
            expected[key] = {"lesson_id": run.lesson_id, "group": run.lesson_group_name,
                "lesson_date": run.lesson_date, "start": None, "available_at": None,
                "schedule_source": "report_log", "marked_reported": False, "runs": []}
        expected[key]["runs"].append(run)
    items, upcoming = [], []
    for item in expected.values():
        evidence = item.pop("runs")
        # A saved occurrence takes precedence over today's editable schedule.
        for run in evidence:
            try:
                snapshot = json.loads(run.lesson_snapshot or "null")
                at = _parse_iso_datetime(snapshot["start_at"]) if isinstance(snapshot, dict) else None
                if at and at.date().isoformat() == item["lesson_date"]:
                    item.update(start=at.isoformat(), schedule_source="saved_occurrence",
                        available_at=(at + timedelta(minutes=int(snapshot.get("duration_minutes") or duration_default) + delay)).isoformat())
                    break
            except (ValueError, TypeError, KeyError):
                pass
        item["runs"] = [_run_data(run) for run in evidence]
        statuses = {run.status for run in evidence}
        if "success" in statuses:
            item["status"] = "sent"
        elif statuses & {"uncertain", "sending"} or any(run.status == "error" and is_ambiguous_error(run.error) for run in evidence):
            item["status"] = "unconfirmed"
        elif "manual_required" in statuses:
            item["status"] = "manual_required"
        elif "error" in statuses:
            item["status"] = "error"
        elif statuses or item["marked_reported"]:
            item["status"] = "unconfirmed"
        else:
            item["status"] = "missing"
        if not evidence and item["available_at"] and _parse_iso_datetime(item["available_at"]) > now:
            item["status"] = "not_due"
            upcoming.append(item)
        else:
            items.append(item)
    items.sort(key=lambda item: (item["lesson_date"], item["group"], item["lesson_id"] or 0))
    counts = dict(Counter(item["status"] for item in items))
    all_sent = (all(item["status"] == "sent" for item in items) if items and not invalid else None)
    return {"checked_at": now.isoformat(), "timezone": "Europe/Kyiv",
        "period": {"start": start.isoformat(), "end": end.isoformat(), "inclusive": True},
        "all_sent": all_sent, "counts": counts, "items": items, "not_due": upcoming,
        "excluded": excluded, "invalid_schedule": invalid,
        "auto_reports_enabled": bool(settings and settings.auto_reports_enabled),
        "verification_scope": "local_schedule_and_delivery_log",
        "limitations": ["Перевірено локальний журнал доставки; історію Telegram повторно не запитували.",
            "Розклад без збереженого знімка відображає поточні налаштування, а не повну історію змін.",
            "Порожня вибірка або некоректний розклад не підтверджують відправлення всіх звітів."]}
