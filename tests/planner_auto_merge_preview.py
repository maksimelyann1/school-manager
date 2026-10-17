"""Legacy conflicts resolved against an isolated in-memory Google calendar."""
from datetime import datetime, timedelta, timezone
import json

import calendar_sync_preview as preview
from models import AppLog
from task_models import PlannerExternalLink, PlannerSyncJob

app = preview.app
frontend_route = app.router.routes.pop()
now = datetime.now(timezone.utc)
with preview.sessions() as db:
    calendar = db.get(preview.PlannerCalendar, 1)
    calendar.sync_format = 3
    for name, local_newer, deleted in [('local-newer', True, False), ('remote-newer', False, False), ('both-deleted', False, True)]:
        old = {'id': name, 'etag': 'old', 'summary': 'Original',
               'updated': (now - timedelta(minutes=10)).isoformat(),
               'start': {'date': preview.day.isoformat()}, 'end': {'date': (preview.day + timedelta(days=1)).isoformat()}}
        preview.google.apply_remote(db, calendar, old)
        db.flush()
        link = db.query(PlannerExternalLink).filter_by(event_id=name).one()
        item = db.get(preview.PlannerItem, link.item_id)
        item.title = 'ТЕСТ · Новіша зміна в програмі' if local_newer else 'ТЕСТ · Старіша зміна в програмі'
        item.updated_at = (now if local_newer else now - timedelta(minutes=5)).isoformat()
        item.revision += 1
        if deleted:
            item.deleted_at = item.updated_at
        preview.events['app'][name] = {**old, 'etag': 'new', 'summary': 'ТЕСТ · Старіша зміна Google' if local_newer else 'ТЕСТ · Новіша зміна Google',
            'updated': (now - timedelta(minutes=5) if local_newer else now).isoformat(),
            **({'status': 'cancelled'} if deleted else {})}
        link.conflict = json.dumps(preview.events['app'][name])
        db.add(PlannerSyncJob(item_id=item.id, connection_id='preview', revision=item.revision,
                             state='conflict', error='Old conflict'))
    db.commit()


@app.get('/api/preview/merge-checks')
def merge_checks():
    with preview.sessions() as db:
        return {'conflicts': db.query(PlannerExternalLink).filter(PlannerExternalLink.conflict.isnot(None)).count(),
                'jobs': db.query(PlannerSyncJob).count(),
                'logs': [row.message for row in db.query(AppLog).filter_by(module='Planner')]}


app.router.routes.append(frontend_route)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8768)
