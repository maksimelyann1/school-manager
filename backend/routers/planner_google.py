import asyncio
import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from task_models import PlannerCalendar, PlannerConnection, PlannerExternalLink, PlannerItem
from services.planner.google_auth import oauth, client_config, config_path, access_token, delete_token, load_token, EVENTS_SCOPE
from services.planner.google_sync import GoogleAPI, sync_google, sync_lock

from services.planner.routes import PlannerRoute
router = APIRouter(prefix='/planner/google', tags=['Google Календар'], route_class=PlannerRoute)


def update_calendar_access(db, calendar, role, events_write):
    calendar.access_role = role
    calendar.writable = int(bool(calendar.managed or (events_write and role in {'owner', 'writer'})))
    for link, item in db.query(PlannerExternalLink, PlannerItem).join(
        PlannerItem, PlannerItem.id == PlannerExternalLink.item_id
    ).filter(PlannerExternalLink.calendar_id == calendar.id).all():
        if item.source != 'google' or item.deleted_at:
            continue
        recurring_instance = bool(json.loads(link.snapshot or '{}').get('recurringEventId'))
        item.read_only = int(not calendar.writable or recurring_instance)
        item.google_enabled = int(bool(calendar.managed or calendar.writable))
        item.google_calendar_id = calendar.id


def active_connection(db):
    connection = db.query(PlannerConnection).filter(PlannerConnection.state.in_(['connected', 'reauth', 'error'])).first()
    if not connection:
        raise HTTPException(409, 'Спочатку підключіть Google')
    return connection


def calendar_marker(account_id):
    return 'School Manager planner ' + hashlib.sha256(account_id.encode()).hexdigest()[:24]


@router.get('/status')
def status(db: Session = Depends(get_db)):
    try:
        client_config()
        configured = True
    except HTTPException:
        configured = False
    connection = db.query(PlannerConnection).filter(PlannerConnection.state.in_(['connected', 'reauth', 'error'])).first()
    calendars = db.query(PlannerCalendar).filter_by(connection_id=connection.id).all() if connection else []
    return {'configured': configured, 'config_path': str(config_path()), 'oauth_state': oauth.state, 'oauth_error': oauth.error,
        'oauth_notice': getattr(oauth, 'notice', None),
        'connection': {'email': connection.email, 'state': connection.state, 'last_sync_at': connection.last_sync_at,
            'next_sync_at': connection.next_sync_at, 'sync_attempts': connection.sync_attempts,
            'error': connection.last_error, 'events_write': bool(connection.events_write)} if connection else None,
        'calendars': [{'id': c.id, 'name': c.name, 'managed': bool(c.managed), 'visible': bool(c.visible),
            'writable': bool(c.writable or c.managed), 'access_role': c.access_role} for c in calendars]}


async def connected(person):
    async with sync_lock:
        with SessionLocal() as db:
            token = await asyncio.to_thread(load_token, person['sub'])
            for connection in db.query(PlannerConnection).filter(PlannerConnection.state != 'disconnected'):
                connection.state = 'disconnected'
            current = db.query(PlannerConnection).filter_by(account_id=person['sub']).first()
            if current is None:
                current = PlannerConnection(id=uuid4().hex, account_id=person['sub'])
                db.add(current)
            current.email, current.state, current.last_error, current.next_sync_at = person.get('email', ''), 'connected', None, None
            current.sync_attempts = 0
            current.events_write = int(EVENTS_SCOPE in (token or {}).get('scope', '').split())
            db.flush()
            for calendar in db.query(PlannerCalendar).filter_by(connection_id=current.id):
                update_calendar_access(db, calendar, calendar.access_role, current.events_write)
            db.commit()


@router.post('/connect')
async def connect():
    return await oauth.start(connected)


@router.post('/cancel')
async def cancel_login():
    await oauth.stop()
    return {'ok': True}


@router.post('/disconnect')
async def disconnect(db: Session = Depends(get_db)):
    await oauth.stop()
    async with sync_lock:
        connection = active_connection(db)
        await asyncio.to_thread(delete_token, connection.account_id)
        connection.state = 'disconnected'
        db.commit()
        oauth.state = 'idle'
    return {'ok': True}


@router.post('/calendars')
async def discover_calendars(db: Session = Depends(get_db)):
    async with sync_lock:
        connection = active_connection(db)
        api = GoogleAPI(await access_token(connection.account_id))
        try:
            values, _ = await api.pages('/users/me/calendarList', {'maxResults': 250})
            restored = []
            for value in values:
                existing = db.query(PlannerCalendar).filter_by(connection_id=connection.id, remote_id=value['id']).first()
                if existing:
                    existing.name = value.get('summary', 'Календар')
                else:
                    existing = PlannerCalendar(connection_id=connection.id, remote_id=value['id'], name=value.get('summary', 'Календар'))
                    db.add(existing)
                    db.flush()
                if (value.get('description') == calendar_marker(connection.account_id)
                        and value.get('accessRole') == 'owner' and not existing.managed):
                    existing.managed, existing.visible = 1, 1
                    restored.append(existing.id)
                    connection.next_sync_at = None
                update_calendar_access(db, existing, value.get('accessRole', 'reader'), connection.events_write)
                existing.color = value.get('backgroundColor')
            db.commit()
            if restored:
                from logger import log_event
                for calendar_id in restored:
                    log_event('INFO', 'Planner', f'Відновлено прив’язку наявного календаря School Manager, ID {calendar_id}')
        finally:
            await api.close()
    return status(db)


@router.post('/calendar')
async def create_calendar(db: Session = Depends(get_db)):
    async with sync_lock:
        connection = active_connection(db)
        existing = db.query(PlannerCalendar).filter_by(connection_id=connection.id, managed=1).first()
        if existing:
            return status(db)
        api = GoogleAPI(await access_token(connection.account_id))
        marker = calendar_marker(connection.account_id)
        try:
            calendars, _ = await api.pages('/users/me/calendarList')
            value = next((c for c in calendars if c.get('description') == marker), None)
            if value is None:
                value = await api.request('POST', '/calendars', json={'summary': 'School Manager', 'description': marker, 'timeZone': 'Europe/Kyiv'})
            record = db.query(PlannerCalendar).filter_by(connection_id=connection.id, remote_id=value['id']).first()
            if record is None:
                record = PlannerCalendar(connection_id=connection.id, remote_id=value['id'], name='School Manager')
                db.add(record)
                db.flush()
            record.managed, record.visible = 1, 1
            update_calendar_access(db, record, 'owner', connection.events_write)
            connection.next_sync_at = None
            db.commit()
        finally:
            await api.close()
    return status(db)


class CalendarChoice(BaseModel):
    visible: bool


@router.patch('/calendars/{calendar_id}')
async def select_calendar(calendar_id: int, payload: CalendarChoice, db: Session = Depends(get_db)):
    async with sync_lock:
        connection = active_connection(db)
        calendar = db.get(PlannerCalendar, calendar_id)
        if not calendar or calendar.connection_id != connection.id:
            raise HTTPException(404, 'Календар не знайдено')
        calendar.visible = 1 if calendar.managed else int(payload.visible)
        connection.next_sync_at = None
        db.commit()
    return status(db)


@router.post('/sync')
async def manual_sync(db: Session = Depends(get_db)):
    await discover_calendars(db)
    return await sync_google(force=True)
