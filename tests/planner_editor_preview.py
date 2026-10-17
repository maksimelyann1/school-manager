"""Simplified calendar editor with legacy fields and Google simulated locally."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import calendar_sync_preview as preview
from models import Group
from services.planner.items import utc_now

app = preview.app
with preview.sessions() as db:
    connection = db.get(preview.PlannerConnection, 'preview')
    connection.state, connection.last_error, connection.sync_attempts = 'connected', None, 0
    db.add(Group(id=600, name='Legacy group', telegram_id='-600'))
    today = datetime.now(ZoneInfo('Europe/Kyiv')).date()
    day = today.isoformat()
    db.add(preview.PlannerItem(id='legacy-hidden-fields', title='ТЕСТ · Збережені налаштування', kind='task',
        category='lesson', status='done', group_id=600, start_date=day, end_date=(today + timedelta(days=1)).isoformat(),
        timezone='America/New_York', created_at=utc_now(), updated_at=utc_now()))
    db.commit()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8768)
