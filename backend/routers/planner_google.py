import asyncio
import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from task_models import PlannerCalendar, PlannerConnection, PlannerExternalLink, PlannerItem, PlannerSyncJob
from services.planner.google_auth import oauth, client_config, config_path, access_token, delete_token
from services.planner.google_sync import GoogleAPI, apply_remote, sync_google, sync_lock
from services.planner.items import queue_sync

from services.planner.routes import PlannerRoute
router = APIRouter(prefix='/planner/google', tags=['Google Календар'], route_class=PlannerRoute)


def active_connection(db):
    connection = db.query(PlannerConnection).filter(PlannerConnection.state.in_(['connected', 'reauth', 'error'])).first()
    if not connection:
        raise HTTPException(409, 'Спочатку підключіть Google')
    return connection


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
        'connection': {'email': connection.email, 'state': connection.state, 'last_sync_at': connection.last_sync_at, 'error': connection.last_error} if connection else None,
        'calendars': [{'id': c.id, 'name': c.name, 'managed': bool(c.managed), 'visible': bool(c.visible)} for c in calendars]}


async def connected(person):
    async with sync_lock:
        with SessionLocal() as db:
            for connection in db.query(PlannerConnection).filter(PlannerConnection.state != 'disconnected'):
                connection.state = 'disconnected'
            current = db.query(PlannerConnection).filter_by(account_id=person['sub']).first()
            if current is None:
                current = PlannerConnection(id=uuid4().hex, account_id=person['sub'])
                db.add(current)
            current.email, current.state, current.last_error, current.next_sync_at = person.get('email', ''), 'connected', None, None
            current.sync_attempts = 0
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
            for value in values:
                existing = db.query(PlannerCalendar).filter_by(connection_id=connection.id, remote_id=value['id']).first()
                if existing:
                    existing.name = value.get('summary', 'Календар')
                else:
                    db.add(PlannerCalendar(connection_id=connection.id, remote_id=value['id'], name=value.get('summary', 'Календар')))
            db.commit()
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
        marker = 'School Manager planner ' + hashlib.sha256(connection.account_id.encode()).hexdigest()[:24]
        try:
            calendars, _ = await api.pages('/users/me/calendarList')
            value = next((c for c in calendars if c.get('description') == marker), None)
            if value is None:
                value = await api.request('POST', '/calendars', json={'summary': 'School Manager', 'description': marker, 'timeZone': 'Europe/Kyiv'})
            record = db.query(PlannerCalendar).filter_by(connection_id=connection.id, remote_id=value['id']).first()
            if record is None:
                record = PlannerCalendar(connection_id=connection.id, remote_id=value['id'], name='School Manager')
                db.add(record)
            record.managed, record.visible = 1, 1
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
async def manual_sync():
    return await sync_google(force=True)


@router.get('/conflicts')
def conflicts(db: Session = Depends(get_db)):
    connection = active_connection(db)
    values = db.query(PlannerExternalLink, PlannerItem).join(PlannerItem, PlannerItem.id == PlannerExternalLink.item_id).join(PlannerCalendar, PlannerCalendar.id == PlannerExternalLink.calendar_id).filter(PlannerCalendar.connection_id == connection.id, PlannerExternalLink.conflict.isnot(None)).all()
    return [{'id': link.id, 'revision': item.revision, 'local_title': item.title, 'local_start': item.start_at or item.start_date,
        'google_title': json.loads(link.conflict).get('summary', 'Видалено в Google'), 'google_start': json.loads(link.conflict).get('start', {})} for link, item in values]


class Resolution(BaseModel):
    revision: int
    use_google: bool


@router.post('/conflicts/{link_id}')
async def resolve_conflict(link_id: int, payload: Resolution, db: Session = Depends(get_db)):
    async with sync_lock:
        connection = active_connection(db)
        link = db.get(PlannerExternalLink, link_id)
        calendar = db.get(PlannerCalendar, link.calendar_id) if link else None
        if not link or not link.conflict or not calendar or calendar.connection_id != connection.id:
            raise HTTPException(404, 'Конфлікт уже вирішено')
        item = db.get(PlannerItem, link.item_id)
        if item.revision != payload.revision:
            raise HTTPException(409, 'Задача змінилася. Перегляньте конфлікт повторно')
        remote = json.loads(link.conflict)
        link.pending_snapshot, link.pending_revision = None, None
        job = db.query(PlannerSyncJob).filter_by(item_id=item.id).first()
        if payload.use_google:
            if job:
                db.delete(job)
                db.flush()
            link.conflict = None
            apply_remote(db, calendar, remote, link)
        else:
            if remote.get('status') == 'cancelled':
                db.delete(link)
                db.flush()
                item.revision += 1
            else:
                link.etag, link.conflict = remote.get('etag'), None
            queue_sync(db, item)
        connection.next_sync_at = None
        db.commit()
    return {'ok': True}
