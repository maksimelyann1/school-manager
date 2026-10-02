import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import random
import time
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException
import httpx
from sqlalchemy import update

from database import SessionLocal
from task_models import PlannerCalendar, PlannerConnection, PlannerExternalLink, PlannerItem, PlannerSyncJob
from services.planner.google_auth import access_token
from services.planner.description import from_google, to_google
from services.planner.items import cancel_reminders, serialize, update_reminders, utc_now, zone

sync_lock = asyncio.Lock()
API = 'https://www.googleapis.com/calendar/v3'
last_activity = 0


def touch_activity():
    global last_activity
    last_activity = time.monotonic()


def equivalent_event(expected, event, calendar):
    if expected.get('status') == 'cancelled':
        return event.get('status') == 'cancelled'
    if event.get('status') == 'cancelled':
        return False
    try:
        a, b = remote_values(expected, calendar), remote_values(event, calendar)
        keys = ('title', 'description', 'kind', 'category', 'status', 'start_date', 'end_date', 'start_at', 'end_at', 'location', 'recurrence')
        emails = lambda value: sorted(x.get('email', '').lower() for x in json.loads(value['attendees']))
        return all(a[key] == b[key] for key in keys) and emails(a) == emails(b) and (
            'conferenceData' not in expected or bool(expected.get('conferenceData')) == bool(event.get('conferenceData')))
    except (ValueError, KeyError):
        return False


class GoogleError(Exception):
    def __init__(self, status, reason=''):
        self.status = status
        self.reason = reason
        super().__init__(f'Google Calendar HTTP {status}')


class GoogleAPI:
    def __init__(self, token):
        self.client = httpx.AsyncClient(timeout=25, headers={'Authorization': f'Bearer {token}'})

    async def request(self, method, path, **kwargs):
        response = await self.client.request(method, API + path, **kwargs)
        if not response.is_success:
            try:
                reason = response.json().get('error', {}).get('message', '')
            except ValueError:
                reason = ''
            raise GoogleError(response.status_code, reason)
        return response.json() if response.content else {}

    async def pages(self, path, params=None):
        values = dict(params or {})
        items, token = [], None
        # A malformed/huge calendar cannot monopolize the desktop indefinitely.
        for _ in range(40):
            page = await self.request('GET', path, params=values)
            items.extend(page.get('items', []))
            if not page.get('nextPageToken'):
                return items, page.get('nextSyncToken')
            values['pageToken'] = page['nextPageToken']
        raise HTTPException(422, 'Завеликий календар. Оберіть менше календарів для перегляду')

    async def close(self):
        await self.client.aclose()


def event_path(calendar, event_id=None):
    path = '/calendars/' + quote(calendar.remote_id, safe='') + '/events'
    return path + '/' + quote(event_id, safe='') if event_id else path


def remote_values(event, calendar):
    start, end = event.get('start', {}), event.get('end', {})
    tz = start.get('timeZone') or 'Europe/Kyiv'
    try:
        zone(tz)
    except HTTPException:
        tz = 'Europe/Kyiv'
    private = event.get('extendedProperties', {}).get('private', {})
    app_event = bool(calendar.managed or private.get('smId'))
    kind = private.get('smKind', 'event') if app_event else 'event'
    kind = kind if kind in {'task', 'event'} else 'event'
    state = private.get('smStatus', 'open') if app_event else 'open'
    state = state if state in {'open', 'done', 'cancelled'} else 'open'
    category = private.get('smCategory', 'event') if app_event else 'event'
    if category not in {'lesson', 'substitution', 'preparation', 'event', 'other'}:
        category = 'event'
    values = dict(title=(event.get('summary') or 'Без назви')[:240], description=from_google(event.get('description'))[:20000],
        location=(event.get('location') or '')[:1000], recurrence=json.dumps(event.get('recurrence') or []),
        attendees=json.dumps(event.get('attendees') or []), meet_requested=int(bool(event.get('conferenceData'))),
        conference_data=json.dumps(event.get('conferenceData')) if event.get('conferenceData') else None,
        kind=kind, category=category, status=state, timezone=tz,
        read_only=int(not (calendar.managed or calendar.writable) or bool(event.get('recurringEventId'))),
        google_enabled=int(bool(calendar.managed or calendar.writable)),
        google_calendar_id=calendar.id,
        start_at=None, end_at=None, start_date=start.get('date'), end_date=end.get('date'))
    if start.get('dateTime'):
        a = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
        b = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
        values.update(start_at=a.astimezone(timezone.utc).isoformat(), end_at=b.astimezone(timezone.utc).isoformat(),
                      start_date=a.astimezone(zone(tz)).date().isoformat(), end_date=b.astimezone(zone(tz)).date().isoformat())
    return values


def event_body(item):
    if item.start_at:
        start = {'dateTime': item.start_at, 'timeZone': item.timezone}
        end = {'dateTime': item.end_at, 'timeZone': item.timezone}
    else:
        start, end = {'date': item.start_date}, {'date': item.end_date}
    body = {'summary': item.title, 'description': to_google(item.description), 'start': start, 'end': end,
        'location': item.location or '', 'recurrence': json.loads(item.recurrence or '[]'),
        'attendees': json.loads(item.attendees or '[]'),
        'extendedProperties': {'private': {'smId': item.id, 'smKind': item.kind, 'smStatus': item.status, 'smCategory': item.category}},
        'reminders': {'useDefault': False}}
    conference = json.loads(item.conference_data or '{}')
    if item.meet_requested:
        if conference and conference.get('createRequest', {}).get('status', {}).get('statusCode') != 'failure':
            body['conferenceData'] = conference
        else:
            body['conferenceData'] = {'createRequest': {'requestId': f'{item.id}-{item.revision}',
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}}}
    elif conference:
        body['conferenceData'] = None
    return body


def changed_event_body(item, snapshot, calendar):
    """Patch only fields actually edited here, retaining Google-only event settings."""
    before = remote_values(snapshot, calendar)
    body = event_body(item)
    result = {}
    fields = {'title': 'summary', 'description': 'description', 'location': 'location',
              'recurrence': 'recurrence', 'attendees': 'attendees'}
    for field, google_field in fields.items():
        if getattr(item, field) != before[field]:
            result[google_field] = body[google_field]
    if any(getattr(item, field) != before[field] for field in ('start_date', 'end_date', 'start_at', 'end_at', 'timezone')):
        result['start'], result['end'] = body['start'], body['end']
    if bool(item.meet_requested) != bool(before['meet_requested']):
        result['conferenceData'] = body.get('conferenceData')
    if any(getattr(item, field) != before[field] for field in ('kind', 'category', 'status')):
        original_properties = snapshot.get('extendedProperties') or {}
        result['extendedProperties'] = {**original_properties,
            'private': {**original_properties.get('private', {}), **body['extendedProperties']['private']}}
    return result


def apply_remote(db, calendar, event, link=None):
    link = link or db.query(PlannerExternalLink).filter_by(calendar_id=calendar.id, event_id=event['id']).first()
    if event.get('status') == 'cancelled' and not event.get('recurringEventId'):
        for occurrence in db.query(PlannerExternalLink).filter_by(calendar_id=calendar.id):
            snapshot = json.loads(occurrence.snapshot or '{}')
            if snapshot.get('recurringEventId') == event['id']:
                apply_remote(db, calendar, {**snapshot, 'id': occurrence.event_id, 'status': 'cancelled', 'etag': event.get('etag', 'series-deleted')}, occurrence)
    if not link and event.get('status') == 'cancelled':
        original = event.get('originalStartTime', {})
        if event.get('recurringEventId') and (original.get('date') or original.get('dateTime')):
            stamp = utc_now()
            tombstone = PlannerItem(id=uuid4().hex, title='Скасоване повторення', source='google', read_only=1,
                                    created_at=stamp, updated_at=stamp, deleted_at=stamp)
            db.add(tombstone)
            db.flush()
            db.add(PlannerExternalLink(item_id=tombstone.id, calendar_id=calendar.id, event_id=event['id'],
                                      etag=event.get('etag'), snapshot=json.dumps(event)))
        return
    if link and link.etag == event.get('etag'):
        if (calendar.sync_format or 0) < 1 and event.get('status') != 'cancelled':
            item = db.get(PlannerItem, link.item_id)
            if item:
                values = remote_values(event, calendar)
                item.conference_data = values['conference_data']
                queued = db.query(PlannerSyncJob).filter_by(item_id=item.id).first()
                if not queued:
                    for key in ('location', 'recurrence', 'attendees', 'meet_requested', 'description'):
                        setattr(item, key, values[key])
                elif values['conference_data']:
                    item.meet_requested = 1
        return
    item = db.get(PlannerItem, link.item_id) if link else None
    if link and not link.etag and event.get('etag') == 'deleted' and link.pending_snapshot:
        return  # A create attempt that never reached Google may safely retry its same ID.
    job = db.query(PlannerSyncJob).filter_by(item_id=item.id).first() if item else None
    if link and link.pending_snapshot:
        expected = json.loads(link.pending_snapshot)
        matches = equivalent_event(expected, event, calendar)
        if matches:
            if event.get('status') != 'cancelled':
                item.conference_data = json.dumps(event.get('conferenceData')) if event.get('conferenceData') else None
            if job and job.revision == link.pending_revision and item.revision == link.pending_revision:
                if event.get('status') != 'cancelled':
                    item.attendees = json.dumps(event.get('attendees') or [])
                db.delete(job)
            link.etag, link.snapshot = event.get('etag'), json.dumps(event)
            link.pending_snapshot, link.pending_revision = None, None
            if event.get('status') == 'cancelled':
                item.source = 'local'
                db.delete(link)
            return
    if job and link and event.get('etag') != link.etag:
        link.conflict = json.dumps(event)
        job.state, job.error = 'conflict', 'Задача змінена і тут, і в Google. Виберіть потрібну версію'
        return
    if event.get('status') == 'cancelled':
        if item:
            previous_revision = item.revision
            changed = db.execute(update(PlannerItem).where(PlannerItem.id == item.id, PlannerItem.revision == previous_revision).values(deleted_at=utc_now(), updated_at=utc_now(), revision=previous_revision + 1))
            if not changed.rowcount:
                link.conflict = json.dumps(event)
                return
            db.refresh(item)
            cancel_reminders(db, item)
            snapshot = {**json.loads(link.snapshot or '{}'), **event}
            link.etag, link.snapshot = event.get('etag'), json.dumps(snapshot)
        return
    values = remote_values(event, calendar)
    if not values['start_date']:
        return
    now = utc_now()
    if item is None:
        item = PlannerItem(id=uuid4().hex, source='google', google_connection_id=calendar.connection_id, created_at=now, updated_at=now, **values)
        db.add(item)
        db.flush()
        link = PlannerExternalLink(item_id=item.id, calendar_id=calendar.id, event_id=event['id'])
        db.add(link)
    else:
        old = serialize(item)
        changed = db.execute(update(PlannerItem).where(PlannerItem.id == item.id, PlannerItem.revision == item.revision).values(**values, deleted_at=None, updated_at=now, revision=item.revision + 1))
        if not changed.rowcount:
            link.conflict = json.dumps(event)
            return
        db.refresh(item)
        update_reminders(db, item, old)
    item.completed_at = now if item.status == 'done' else None
    link.etag, link.snapshot, link.conflict = event.get('etag'), json.dumps(event), None


async def pull_calendar(db, api, calendar):
    now = datetime.now(timezone.utc)
    format_version = 2 if calendar.writable and not calendar.managed else 1
    upgrading = (calendar.sync_format or 0) < format_version
    if upgrading:
        calendar.sync_token = None
    if calendar.sync_window_start and now - datetime.fromisoformat(calendar.sync_window_start) > timedelta(days=28):
        calendar.sync_token = None
    initial = not calendar.sync_token
    params = {'maxResults': 2500, 'singleEvents': 'false' if calendar.managed or calendar.writable else 'true', 'showDeleted': 'true'}
    if initial:
        if not calendar.managed:
            params.update(timeMin=(now - timedelta(days=90)).isoformat(), timeMax=(now + timedelta(days=366)).isoformat())
    else:
        params['syncToken'] = calendar.sync_token
    try:
        events, token = await api.pages(event_path(calendar), params)
    except GoogleError as err:
        if err.status != 410 or initial:
            raise
        calendar.sync_token = None
        db.commit()
        return await pull_calendar(db, api, calendar)
    # All pages succeeded before advancing the token. Queued edits survive a full refresh.
    db.expire_all()
    confirmations = []
    if initial:
        known_ids = {event['id'] for event in events}
        for link in db.query(PlannerExternalLink).filter_by(calendar_id=calendar.id).all():
            item = db.get(PlannerItem, link.item_id)
            if upgrading and link.event_id not in known_ids and json.loads(link.snapshot or '{}').get('recurringEventId'):
                if item:
                    item.deleted_at = utc_now()
                db.delete(link)
                continue
            if item and item.start_date and (now - timedelta(days=90)).date().isoformat() <= item.start_date < (now + timedelta(days=366)).date().isoformat() and link.event_id not in known_ids:
                # Confirm deletion/move individually; absence from a window is not deletion.
                try:
                    event = await api.request('GET', event_path(calendar, link.event_id))
                except GoogleError as err:
                    if err.status not in {404, 410}:
                        raise
                    event = {'id': link.event_id, 'status': 'cancelled', 'etag': 'deleted'}
                confirmations.append((link, event))
        calendar.sync_window_start = now.isoformat()
    for event in events:
        apply_remote(db, calendar, event)
        db.flush()
    for link, event in confirmations:
        apply_remote(db, calendar, event, link)
    calendar.sync_token, calendar.last_sync_at = token, utc_now()
    calendar.sync_format = format_version
    db.commit()


async def push_job(db, api, calendar, job):
    item = db.get(PlannerItem, job.item_id)
    if not item or item.read_only or not (calendar.managed or calendar.writable) or job.state == 'conflict' or (job.connection_id and job.connection_id != calendar.connection_id) or (item.google_connection_id and item.google_connection_id != calendar.connection_id):
        return
    link = db.query(PlannerExternalLink).filter_by(item_id=item.id).first()
    if link and link.calendar_id != calendar.id:
        return  # Never move an old account's edits into a different account/calendar.
    revision = item.revision
    if link and link.conflict:
        return
    removing = bool(item.deleted_at or not item.google_enabled)
    if removing and not link:
        db.delete(job); db.commit(); return
    event_id = link.event_id if link else 'sm' + hashlib.sha256((calendar.remote_id + item.id + str(revision)).encode()).hexdigest()[:48]
    body = event_body(item)
    if not calendar.managed and not link:
        body.pop('reminders', None)  # Respect the selected calendar's default notifications.
    if link and link.etag:
        body = changed_event_body(item, json.loads(link.snapshot or '{}'), calendar)
        if not removing and not body:
            db.delete(job); db.commit(); return
    if not link:
        link = PlannerExternalLink(item_id=item.id, calendar_id=calendar.id, event_id=event_id)
        db.add(link)
    link.pending_snapshot = json.dumps({'status': 'cancelled'} if removing else {**json.loads(link.snapshot or '{}'), **body} if link.etag else body)
    link.pending_revision = revision
    job.connection_id = calendar.connection_id
    item.google_connection_id = calendar.connection_id
    db.commit()  # Persist the operation identity before any network write.
    try:
        if removing:
            try:
                await api.request('DELETE', event_path(calendar, event_id), headers={'If-Match': link.etag or '*'}, params={'sendUpdates': 'all'})
            except GoogleError as err:
                if err.status not in {404, 410}:
                    raise
            db.refresh(item)
            if item.revision != revision:
                # Retain a pending job; restore must recreate with a fresh remote ID.
                db.delete(link)
                item.source = 'local'
                db.commit()
                return
            db.delete(link)
            item.source = 'local'
        else:
            if link.etag:
                event = await api.request('PATCH', event_path(calendar, event_id), json=body, headers={'If-Match': link.etag or '*'}, params={'sendUpdates': 'all', 'conferenceDataVersion': 1})
            else:
                try:
                    event = await api.request('POST', event_path(calendar), json={**body, 'id': event_id}, params={'sendUpdates': 'all', 'conferenceDataVersion': 1})
                except GoogleError as err:
                    if err.status != 409:
                        raise
                    event = await api.request('GET', event_path(calendar, event_id))
                    if not equivalent_event(body, event, calendar):
                        link.conflict = json.dumps(event)
                        job.state = 'conflict'
                        db.commit()
                        return
            link.etag, link.snapshot = event.get('etag'), json.dumps(event)
            link.pending_snapshot, link.pending_revision = None, None
        db.refresh(item)
        db.refresh(job)
        if not removing:
            item.conference_data = json.dumps(event.get('conferenceData')) if event.get('conferenceData') else None
        if item.revision == revision and job.revision == revision:
            if not removing:
                item.attendees = json.dumps(event.get('attendees') or [])
            db.delete(job)
        db.commit()
    except GoogleError as err:
        if err.status in {404, 410, 412} and link:
            event = ({'id': event_id, 'status': 'cancelled', 'etag': 'deleted'} if err.status in {404, 410} else await api.request('GET', event_path(calendar, event_id)))
            link.conflict = json.dumps(event)
            job.state, job.error = 'conflict', 'Задача змінена і тут, і в Google. Виберіть потрібну версію'
            db.commit()
        else:
            raise


async def sync_google(force=False):
    if sync_lock.locked():
        return {'state': 'busy'}
    async with sync_lock:
        db = SessionLocal()
        api = None
        try:
            connection = db.query(PlannerConnection).filter(PlannerConnection.state.in_(['connected', 'error'] if force else ['connected'])).first()
            if not connection:
                return {'state': 'disconnected'}
            now = utc_now()
            if not force and connection.next_sync_at and connection.next_sync_at > now:
                return {'state': 'waiting'}
            api = GoogleAPI(await access_token(connection.account_id))
            calendars = db.query(PlannerCalendar).filter_by(connection_id=connection.id).all()
            for calendar in calendars:
                if calendar.managed or calendar.visible:
                    await pull_calendar(db, api, calendar)
            if calendars:
                jobs = db.query(PlannerSyncJob).filter(PlannerSyncJob.state.notin_(['conflict', 'error']),
                    (PlannerSyncJob.connection_id == connection.id) | PlannerSyncJob.connection_id.is_(None)).limit(50).all()
                for job in jobs:
                    if not job.next_attempt_at or job.next_attempt_at <= now:
                        item = db.get(PlannerItem, job.item_id)
                        link = db.query(PlannerExternalLink).filter_by(item_id=job.item_id).first()
                        calendar_id = link.calendar_id if link else item.google_calendar_id if item else None
                        calendar = next((cal for cal in calendars if cal.id == calendar_id), None)
                        if not calendar:
                            calendar = next((cal for cal in calendars if cal.managed), None) if calendar_id is None else None
                        if not calendar or not (calendar.managed or calendar.writable):
                            continue
                        try:
                            await push_job(db, api, calendar, job)
                        except GoogleError as err:
                            if err.status != 400:
                                raise
                            job.state = 'error'
                            job.error = ('Цей календар не підтримує Google Meet. Приберіть Meet і збережіть подію повторно.'
                                if 'conference' in err.reason.lower() else 'Google відхилив параметри події. Перевірте гостей і повторення та збережіть знову.')
                            link = db.query(PlannerExternalLink).filter_by(item_id=job.item_id).first()
                            if link:
                                link.pending_snapshot, link.pending_revision = None, None
                                if not link.etag:
                                    db.delete(link)
                            db.commit()
            connection.last_sync_at, connection.last_error = utc_now(), None
            connection.state, connection.sync_attempts = 'connected', 0
            interval = 5 if time.monotonic() - last_activity < 90 else 15
            connection.next_sync_at = (datetime.now(timezone.utc) + timedelta(minutes=interval)).isoformat()
            pending_meet = db.query(PlannerItem).filter_by(google_connection_id=connection.id, deleted_at=None, meet_requested=1).all()
            if any(json.loads(item.conference_data or '{}').get('createRequest', {}).get('status', {}).get('statusCode') == 'pending' for item in pending_meet):
                connection.next_sync_at = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
            db.commit()
            return {'state': 'connected'}
        except Exception as err:
            db.rollback()
            from logger import log_event
            status = err.status if isinstance(err, GoogleError) else err.status_code if isinstance(err, HTTPException) else 0
            message = ('Доступ Google завершився. Підключіть акаунт повторно' if status == 401 else
                'Google тимчасово обмежив запити. Синхронізація повториться пізніше' if status in {403, 429} else
                'Не вдалося синхронізувати Google Календар. Зміни збережено на комп’ютері')
            connection = db.query(PlannerConnection).filter(PlannerConnection.state.in_(['connected', 'error'])).first()
            if connection:
                if connection.last_error != message:
                    log_event('ERROR', 'Planner', f'{message} ({type(err).__name__}, HTTP {status})')
                connection.last_error = message
                connection.sync_attempts += 1
                delay = min(3600, 60 * 2 ** min(connection.sync_attempts, 6)) + random.randint(0, 30)
                connection.next_sync_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                if status == 401:
                    connection.state = 'reauth'
                elif connection.sync_attempts >= 6:
                    connection.state = 'error'
                    connection.last_error += '. Автоповтори призупинено; натисніть «Синхронізувати»'
                db.commit()
            return {'state': 'error', 'error': message}
        finally:
            if api:
                await api.close()
            db.close()
