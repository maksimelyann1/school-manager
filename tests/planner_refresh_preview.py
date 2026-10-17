"""Refresh/filter UI with disposable data and controllable response latency."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import calendar_sync_preview as preview
from services.planner.items import utc_now

app = preview.app
delays = {'tasks': 20, 'google': 20}
requests = []
frontend_route = app.router.routes.pop()


@app.middleware('http')
async def latency(request, call_next):
    path = request.url.path
    kind = 'tasks' if path == '/api/tasks' else 'google' if path.startswith('/api/planner/google/') and request.method != 'GET' else None
    if kind:
        requests.append({'path': path, 'query': str(request.url.query), 'method': request.method})
        await asyncio.sleep(delays[kind] / 1000)
    return await call_next(request)


@app.post('/api/preview/delay')
def delay(values: dict):
    for name in delays:
        if name in values:
            delays[name] = max(0, min(2000, int(values[name])))
    return delays


@app.get('/api/preview/requests')
def request_log():
    return requests


with preview.sessions() as db:
    connection = db.get(preview.PlannerConnection, 'preview')
    connection.state, connection.last_error, connection.sync_attempts = 'connected', None, 0
    connection.last_sync_at = utc_now()
    day = datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat()
    for identity, title, status in [('refresh-open', 'ТЕСТ · Відкрита задача', 'open'),
                                    ('refresh-done', 'ТЕСТ · Виконана задача', 'done')]:
        db.add(preview.PlannerItem(id=identity, title=title, kind='task', category='preparation', status=status,
                                  start_date=day, end_date=day, created_at=utc_now(), updated_at=utc_now()))
    db.commit()

app.router.routes.append(frontend_route)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8768)
