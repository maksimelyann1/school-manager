"""Isolated visual preview: synthetic data, no Telegram, OAuth, scheduler or user database."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from routers import tasks, planner_google

ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix='school-manager-planner-')
engine = create_engine(f'sqlite:///{TEMP.name}/preview.db', connect_args={'check_same_thread': False})
Base.metadata.create_all(engine)
sessions = sessionmaker(bind=engine, autoflush=False)
@asynccontextmanager
async def lifespan(app):
    yield
    engine.dispose()
    TEMP.cleanup()
app = FastAPI(lifespan=lifespan)
def preview_db():
    with sessions() as db:
        yield db
app.dependency_overrides[get_db] = preview_db
app.include_router(tasks.router, prefix='/api')
# Read-only status to demonstrate unconfigured OAuth; no external mutations in preview.
app.add_api_route('/api/planner/google/status', planner_google.status)
with sessions() as db:
    day = datetime.now(ZoneInfo('Europe/Kyiv')).date()
    for title, category, hour, shift in [('Урок · Фронтенд', 'lesson', '14:00', 0), ('Підготувати приклад з Grid', 'preparation', '12:00', 0), ('Заміна · Python Start', 'substitution', '16:30', 1), ('Підготовка до відкритого уроку', 'event', '11:00', 2)]:
        tasks.create_task(tasks.CreateTask(title=title, kind='task' if category == 'preparation' else 'event', category=category, date=(day + timedelta(days=shift)).isoformat(), time=hour), db)
    tasks.create_task(tasks.CreateTask(title='Знайти приклади для нового проєкту'), db)
@app.get('/api/settings/bot')
def telegram_status():
    return {'is_connected': False, 'has_session': False}
@app.get('/api/groups')
def groups():
    return []
@app.post('/api/logs/client')
def logs():
    return {'ok': True}
app.mount('/assets', StaticFiles(directory=ROOT / 'frontend/dist-new/assets'), name='assets')
@app.get('/{path:path}')
def frontend(path: str):
    root = (ROOT / 'frontend/dist-new').resolve()
    asset = (root / path).resolve()
    if asset.is_relative_to(root) and asset.is_file():
        return FileResponse(asset)
    return FileResponse(ROOT / 'frontend/dist-new/index.html')
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8766)
