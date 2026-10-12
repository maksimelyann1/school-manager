"""Widget preview with a disposable database and no connected services."""
from datetime import datetime, timedelta
from planner_preview import app, sessions
from routers import widgets
from models import ParentReportLesson
from routers.parents_report import KYIV_TZ

frontend_route = app.router.routes.pop()
app.include_router(widgets.router, prefix='/api')
with sessions() as db:
    now = datetime.now(KYIV_TZ)
    for title, day, time, paused, postponed in [('Фронтенд · субота', 'СБ', '14:00', 0, None), ('Python · індивідуально', 'НД', '10:00', 0, None), ('Дизайн · перенесено', 'ЧТ', '18:00', 0, (now + timedelta(days=10)).isoformat()), ('Група на паузі', 'НД', '12:00', 1, None)]:
        db.add(ParentReportLesson(group_name=title, day=day, start_time=time, is_paused=paused,
            lesson_code='М2У4', lesson_title='Практична робота', postponed_start_at=postponed))
    db.commit()

@app.get('/api/settings/interface')
def interface(): return {'sidebar_collapsed': False}

@app.get('/api/startup')
def startup(): return {'ready': True, 'status': 'ready', 'tasks': []}

app.router.routes.append(frontend_route)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8769)
