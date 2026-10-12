"""Calendar UI with an isolated database and an in-memory Google substitute."""
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from planner_preview import app, engine, sessions, TEMP
from routers import planner_google
from services.planner import google_sync as google
from task_models import PlannerCalendar, PlannerConnection, PlannerItem, PlannerSyncJob

day = datetime.now(ZoneInfo('Europe/Kyiv')).date()
events = {'app': {}, 'primary': {}, 'holidays': {}}
events['primary']['imported'] = {'id': 'imported', 'etag': 'v1', 'summary': 'ТЕСТ · Урок із Google',
    'start': {'dateTime': f'{day}T15:00:00+03:00', 'timeZone': 'Europe/Kyiv'},
    'end': {'dateTime': f'{day}T16:00:00+03:00', 'timeZone': 'Europe/Kyiv'}}
events['holidays']['holiday'] = {'id': 'holiday', 'etag': 'v1', 'summary': 'ТЕСТ · Свято',
    'start': {'date': day.isoformat()}, 'end': {'date': (day + timedelta(days=1)).isoformat()}}
calls, client_errors = [], []

class FakeGoogle:
    async def pages(self, path, params=None):
        if path == '/users/me/calendarList':
            return ([{'id': key, 'summary': name, 'accessRole': role} for key, name, role in
                     [('app', 'School Manager', 'owner'), ('primary', 'Мій календар', 'owner'), ('holidays', 'Свята', 'reader')]], None)
        calendar = path.split('/')[2]
        return list(events[calendar].values()), 'new-sync-token'

    async def request(self, method, path, **kwargs):
        calendar = path.split('/')[2]
        event_id = path.split('/')[-1]
        body = kwargs.get('json', {})
        calls.append({'method': method, 'calendar': calendar, 'body': body})
        if method == 'POST':
            event_id = body['id']
            events[calendar][event_id] = {**body, 'etag': 'v1'}
        elif method == 'PATCH':
            events[calendar][event_id] = {**events[calendar][event_id], **body, 'etag': 'v2'}
        elif method == 'DELETE':
            events[calendar][event_id] = {**events[calendar][event_id], 'status': 'cancelled', 'etag': 'deleted'}
            return {}
        return events[calendar][event_id]

    async def close(self):
        pass

@asynccontextmanager
async def lifespan(app):
    with ExitStack() as stack:
        stack.enter_context(patch.object(google, 'SessionLocal', sessions))
        for module in (google, planner_google):
            stack.enter_context(patch.object(module, 'access_token', AsyncMock(return_value='fake')))
            stack.enter_context(patch.object(module, 'GoogleAPI', side_effect=lambda *args: FakeGoogle()))
        stack.enter_context(patch.object(planner_google, 'client_config', return_value={'client_id': 'fake'}))
        stack.enter_context(patch.object(planner_google, 'oauth', SimpleNamespace(state='connected', error=None,
            start=AsyncMock(return_value={'state': 'waiting'}), stop=AsyncMock())))
        stack.enter_context(patch('logger.log_event', lambda *args: None))
        yield
    engine.dispose()
    TEMP.cleanup()

app.router.lifespan_context = lifespan
frontend_route = app.router.routes.pop()
app.router.routes = [route for route in app.router.routes if getattr(route, 'path', None) not in
                     {'/api/planner/google/status', '/api/logs/client'}]
app.include_router(planner_google.router, prefix='/api')
with sessions() as db:
    db.add(PlannerConnection(id='preview', account_id='fake-account', email='preview@example.test',
        state='error', sync_attempts=6, last_error='ТЕСТ · Попередня синхронізація не вдалася',
        next_sync_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), events_write=1))
    db.add_all(PlannerCalendar(id=n, connection_id='preview', remote_id=remote, name=name,
        managed=int(n == 1), visible=1, writable=int(n != 3), access_role='reader' if n == 3 else 'owner')
        for n, remote, name in [(1, 'app', 'School Manager'), (2, 'primary', 'Мій календар'), (3, 'holidays', 'Свята')])
    db.commit()

@app.post('/api/logs/client')
def client_log(payload: dict):
    client_errors.append(payload)
    return {'ok': True}

@app.get('/api/preview/checks')
def checks():
    with sessions() as db:
        return {'state': db.get(PlannerConnection, 'preview').state,
            'jobs': db.query(PlannerSyncJob).count(), 'calls': calls, 'client_errors': client_errors,
            'items': [{'id': i.id, 'title': i.title, 'revision': i.revision, 'deleted': bool(i.deleted_at),
                       'calendar': i.google_calendar_id} for i in db.query(PlannerItem)], 'events': events}

@app.post('/api/preview/remote-change')
def remote_change():
    events['primary']['imported'].update(summary='ТЕСТ · Змінено в Google', etag='v3')
    return {'ok': True}

app.router.routes.append(frontend_route)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8768)
