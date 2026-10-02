"""Expand series in their wall-clock timezone, including Google's exceptions."""
from datetime import datetime, time, timedelta, timezone
import json
import re

from dateutil.rrule import rrulestr
from fastapi import HTTPException

from task_models import PlannerExternalLink, PlannerItem
from services.planner.items import serialize_many, zone


def recurrence_rule(lines, start):
    if any(len(line) > 2000 or not line.startswith(('RRULE:', 'EXDATE', 'RDATE')) for line in lines):
        raise ValueError('Invalid recurrence')
    for line in lines:
        if line.startswith('RRULE:') and not re.search(r'(?:^|;)FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)(?:;|$)', line[6:]):
            raise ValueError('Unsupported frequency')
    return rrulestr('\n'.join(lines), dtstart=start, forceset=True)


def normalize_recurrence(lines, values):
    result = []
    for line in lines:
        match = re.search(r';UNTIL=(\d{8})(?:T\d{6}Z)?', line)
        if match:
            if values.get('start_at') and 'T' not in match[0].split('=')[1]:
                last = datetime.strptime(match[1], '%Y%m%d').replace(hour=23, minute=59, second=59, tzinfo=zone(values['timezone']))
                line = line.replace(match[0], last.astimezone(timezone.utc).strftime(';UNTIL=%Y%m%dT%H%M%SZ'))
            elif not values.get('start_at') and 'T' in match[0].split('=')[1]:
                last = datetime.strptime(match[0].split('=')[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).astimezone(zone(values['timezone']))
                line = line.replace(match[0], last.strftime(';UNTIL=%Y%m%d'))
        result.append(line)
    return result


def validate_recurrence(lines, values):
    if not lines:
        return
    if not values.get('start_date'):
        raise HTTPException(422, 'Для повторення потрібна дата')
    try:
        start = (datetime.fromisoformat(values['start_at']).astimezone(zone(values['timezone']))
                 if values.get('start_at') else datetime.fromisoformat(values['start_date']))
        rule = recurrence_rule(lines, start)
        if next(iter(rule), None) is None:
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(422, 'Перевірте налаштування повторення')


def occurrence_key(value):
    if 'T' not in value:
        return value
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()


def expand_calendar(items, db, start_day, end_day, display_zone):
    rows = serialize_many(items, db)
    series_ids = {row['id'] for row in rows if row['recurrence']}
    links = db.query(PlannerExternalLink).all()
    linked_items = {(link.calendar_id, link.event_id): link.item_id for link in links}
    masters = {(link.calendar_id, link.event_id): link.item_id for link in links if link.item_id in series_ids}
    exceptions = {}
    hidden = set()
    for link in links:
        event = json.loads(link.snapshot or '{}')
        parent_id = linked_items.get((link.calendar_id, event.get('recurringEventId')))
        if parent_id:
            parent = db.get(PlannerItem, parent_id)
            if parent and (parent.deleted_at or parent.status == 'cancelled' or not json.loads(parent.recurrence or '[]')):
                hidden.add(link.item_id)
        master_id = masters.get((link.calendar_id, event.get('recurringEventId')))
        original = event.get('originalStartTime', {})
        original_start = original.get('dateTime') or original.get('date')
        if master_id and original_start:
            exceptions.setdefault(master_id, set()).add(occurrence_key(original_start))
    result = []
    for row in rows:
        if row['id'] in hidden:
            continue
        if not row['recurrence']:
            result.append(row)
            continue
        local_zone = zone(row['timezone'])
        start = datetime.fromisoformat(row['start'])
        finish = datetime.fromisoformat(row['end'])
        if not row['all_day']:
            start, finish = start.astimezone(local_zone), finish.astimezone(local_zone)
        duration = finish - start
        lower = datetime.combine(start_day, time(), tzinfo=display_zone)
        upper = datetime.combine(end_day, time(), tzinfo=display_zone)
        if row['all_day']:
            lower, upper = lower.replace(tzinfo=None), upper.replace(tzinfo=None)
        try:
            rule = recurrence_rule(row['recurrence'], start)
            count = 0
            for occurrence in rule.xafter(lower - duration, inc=True):
                if occurrence >= upper:
                    break
                count += 1
                if count > 1000:
                    raise HTTPException(422, 'Забагато повторень у цьому періоді')
                end = occurrence + duration
                if end <= lower:
                    continue
                if not row['all_day'] and occurrence.astimezone(timezone.utc).astimezone(local_zone).replace(tzinfo=None) != occurrence.replace(tzinfo=None):
                    continue
                key = occurrence.date().isoformat() if row['all_day'] else occurrence_key(occurrence.isoformat())
                if key in exceptions.get(row['id'], set()):
                    continue
                result.append({**row, 'series_master': row, 'occurrence_id': f"{row['id']}@{key}",
                    'start': occurrence.date().isoformat() if row['all_day'] else occurrence.astimezone(timezone.utc).isoformat(),
                    'end': end.date().isoformat() if row['all_day'] else end.astimezone(timezone.utc).isoformat(),
                    'date': occurrence.date().isoformat(),
                    'end_date': (end - timedelta(days=1)).date().isoformat() if row['all_day'] else end.date().isoformat(),
                    'time': None if row['all_day'] else occurrence.strftime('%H:%M'),
                    'end_time': None if row['all_day'] else end.strftime('%H:%M')})
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(422, f"Не вдалося прочитати повторення події «{row['title']}»")
    return sorted(result, key=lambda row: (row['start'] or '', row['id']))
