"""Notification destinations with fake accounts and a temporary database."""
from datetime import datetime, timedelta, timezone
from report_resend_preview import app, engine, sessions
from database import Base
from routers import tasks
from task_models import PlannerItem, PlannerReminder

TASK_ID = 'a2111111111141118111111111111111'
frontend_route = app.router.routes.pop()
app.include_router(tasks.router, prefix='/api')
Base.metadata.create_all(engine)
now = datetime.now(timezone.utc)
day = (now + timedelta(days=3)).date().isoformat()
with sessions() as db:
    db.add(PlannerItem(id=TASK_ID, title='ТЕСТ · Підготовка до уроку',
                       description='Дані саме тієї задачі, на нагадування якої натиснули.',
                       start_date=day, end_date=(now + timedelta(days=4)).date().isoformat(),
                       created_at=now.isoformat(), updated_at=now.isoformat()))
    db.add(PlannerReminder(item_id=TASK_ID, channel='system', state='missed',
                           remind_at=(now - timedelta(hours=2)).isoformat(), updated_at=now.isoformat()))
    db.commit()


@app.get('/api/planner/google/status')
def google():
    return {'configured': True, 'connection': None, 'calendars': [], 'oauth_state': None}


@app.get('/api/auto-messages/')
def messages():
    return [{'id': 1, 'group_id': 1, 'message': 'ТЕСТ · Повідомлення перед уроком',
             'send_day': 'mon', 'send_time': '18:00', 'repeat_count': 1, 'sent_count': 0,
             'is_active': 1, 'source': 'manual', 'files': [], 'stickers': []}]


@app.get('/api/templates/')
def templates():
    return []


app.router.routes.append(frontend_route)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8767)
