"""Browser preview with an isolated database and fake Logika, AI and Telegram."""
import asyncio
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from models import Group, LogikaSettings, ParentReportCourse, ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import dashboard, parents_report as reports

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PREVIEW = '--schedule' in sys.argv
TEMP = tempfile.TemporaryDirectory(prefix='school-manager-resend-')
engine = create_engine(f'sqlite:///{TEMP.name}/preview.db', connect_args={'check_same_thread': False})
Base.metadata.create_all(engine)
sessions = sessionmaker(bind=engine, autoflush=False)
sent = []
client_errors = []
course = 'Фронтенд Н_П'
logika = Mock(access_token='fake', refresh_token=None, xsrf_token=None)
logika.get_group_schedule.return_value = [{
    'id': 101, 'group': {'key': 77}, 'teacher': {'key': 22}, 'contentType': 'GROUP',
    'start': '2026-09-01T14:00:00+03:00', 'duration': 5400, 'lessonStatus': 'FINISH',
    'lesson': {'value': 'М2У5 Тема з платформи'}, 'studentsAmount': 2,
}]
logika.get_attendance.side_effect = lambda schedule_id: [
    {'scheduleId': schedule_id, 'studentId': {'key': n, 'value': f'Учень {n}'}, 'state': 'PRESENT'}
    for n in (1, 2)
]

async def generate(settings, lesson, absents, **kwargs):
    await asyncio.sleep(0.15)
    values = reports._context_values(lesson, settings, absents)
    return f"Звіт за {values['date']} · {values['lesson_code']} · Відсутні: {absents or 'немає'}"

async def send(client, chat_id, message, random_id, label):
    await asyncio.sleep(0.3)
    sent.append({'chat_id': chat_id, 'message': message, 'random_id': random_id})
    return {'ok': True, 'message_id': len(sent) + 100}

@asynccontextmanager
async def lifespan(app):
    with ExitStack() as stack:
        stack.enter_context(patch.object(reports, 'pyrogram_manager', SimpleNamespace(is_connected=True, client=object())))
        stack.enter_context(patch.object(dashboard, 'pyrogram_manager', SimpleNamespace(is_connected=True)))
        stack.enter_context(patch.object(reports, 'log_event', lambda *args: None))
        stack.enter_context(patch.object(reports, '_generate_ai_report', generate))
        stack.enter_context(patch.object(reports, 'send_report_message', send))
        stack.enter_context(patch.object(reports, '_load_source_course_lessons', AsyncMock(return_value={course: [{
            'lesson_code': 'М2У5', 'lesson_count': 9, 'lesson_title': 'Логічні вирази',
            'lesson_report_text': 'Матеріал із бази звітів',
        }]})))
        stack.enter_context(patch('logika_client.LogikaClient', return_value=logika))
        yield
    engine.dispose()
    TEMP.cleanup()

app = FastAPI(lifespan=lifespan)
def preview_db():
    with sessions() as db:
        yield db
app.dependency_overrides[get_db] = preview_db
app.include_router(reports.router, prefix='/api')
app.include_router(dashboard.router, prefix='/api')
with sessions() as db:
    group = Group(name='ТЕСТ · Telegram', telegram_id='-123')
    db.add(group)
    db.flush()
    lesson = ParentReportLesson(group_name='Фронтенд · СБ 14:00', telegram_group_id=group.id,
                                day='СБ', start_time='14:00', duration_minutes=90, course=course,
                                lesson_code='М2У4', lesson_count='8', last_report_date='08-09-2026',
                                absents='Введено для наступного уроку', logika_group_id=77, logika_schedule_id=108)
    if SCHEDULE_PREVIEW:
        lesson.is_paused = 1
        db.add(ParentReportLesson(group_name='Кузнецова_Академ_Scratch_Чт_16:00', day='ЧТ', start_time='16:00',
                                 telegram_group_id=group.id, course=course, lesson_code='М5У1', lesson_count='17',
                                 postponed_start_at='2026-11-01T16:00:00+02:00', postponed_from_date='2026-10-08'))
    db.add_all([lesson, ParentReportSettings(google_ai_api_key='fake', absent_followup_enabled=0,
                                           auto_reports_enabled=int(SCHEDULE_PREVIEW)),
                ParentReportCourse(name=course, row_order=1),
                LogikaSettings(login='fake', password='fake', access_token='fake', teacher_id=22)])
    db.flush()
    original = ParentReportLesson(**{name: getattr(lesson, name) for name in reports.REPORT_SNAPSHOT_FIELDS})
    original.lesson_code, original.lesson_count, original.logika_schedule_id = 'М2У5', '9', 101
    db.add(ParentReportRun(lesson_id=lesson.id, lesson_group_name=lesson.group_name, lesson_date='2026-09-01',
                          telegram_group_id=group.id, status='success', message='Попередній звіт', absents='Учень 2',
                          is_auto=1, is_test=0, created_at='2026-09-01T15:40:00+03:00',
                          lesson_snapshot=reports._report_snapshot(original, {'start_dt': datetime(2026, 9, 1, 14, tzinfo=reports.KYIV_TZ)})))
    db.commit()

@app.get('/api/settings/bot')
def bot(): return {'is_connected': True, 'has_session': False}
@app.get('/api/settings/interface')
def interface(): return {'sidebar_collapsed': False}
@app.get('/api/startup')
def startup(): return {'steps': {}, 'finished': True}
@app.get('/api/system/version')
def version(): return {'current_version': '2.11', 'update_available': False, 'check_enabled': False}
@app.get('/api/groups/')
def groups(): return [{'id': 1, 'name': 'ТЕСТ · Telegram', 'telegram_id': '-123'}]
@app.post('/api/logs/client')
def logs(body: dict):
    client_errors.append(body)
    return {'ok': True}
@app.get('/api/preview-checks')
def checks():
    with sessions() as db:
        lesson = db.get(ParentReportLesson, 1)
        return {'sent': sent, 'client_errors': client_errors, 'runs': reports.get_report_runs(db=db),
                'lesson': {name: getattr(lesson, name) for name in ('lesson_code', 'lesson_count', 'last_report_date', 'absents')},
                'schedule': [reports._serialize_lesson(row) for row in db.query(ParentReportLesson).all()],
                'next_auto_report': dashboard.get_dashboard_stats(db=db)['reports_info']['next_auto_report']}

app.mount('/assets', StaticFiles(directory=ROOT / 'frontend/dist-new/assets'), name='assets')
@app.get('/{path:path}')
def frontend(path: str):
    root = (ROOT / 'frontend/dist-new').resolve()
    asset = (root / path).resolve()
    return FileResponse(asset if asset.is_relative_to(root) and asset.is_file() else root / 'index.html')
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8767)
