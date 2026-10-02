# Головний файл FastAPI додатку
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import HTTPException
import os
import asyncio
from startup_state import startup_state

from database import engine, Base, SessionLocal, ensure_schema_migrations
from models import Group, BotSettings, AutoMessage, Template, Category, LogikaSettings, ParentReportLesson
from routers import groups, settings, messages, auto_messages, templates, categories, logs, dashboard, files, stickers, parents_report, ai, logika
from routers import system
from routers import tasks
from routers import planner_google
from pyrogram_client import pyrogram_manager
from telegram_credentials import get_effective_credentials, stored_credentials_match_default


ALLOWED_LOCAL_ORIGINS = {
    "http://127.0.0.1:8001",
    "http://localhost:8001",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
}


async def _startup_telegram():
    from logger import log_event
    db = SessionLocal()
    try:
        db_settings = db.query(BotSettings).first()
        if db_settings and stored_credentials_match_default(db_settings):
            db_settings.api_id = None
            db_settings.api_hash = None
            db.commit()
        credentials = get_effective_credentials(db_settings)
    finally:
        db.close()
    if not credentials or not pyrogram_manager.has_session():
        startup_state.set("telegram", "skipped", "Telegram: потрібен вхід у налаштуваннях")
        return
    startup_state.set("telegram", "running", "Підключаємо Telegram…")
    connected = await pyrogram_manager.connect_with_session(credentials.api_id, credentials.api_hash)
    if not connected:
        raise RuntimeError("Не вдалося підключити збережену Telegram-сесію")
    startup_state.set("telegram", "running", "Відновлюємо заплановані повідомлення…")
    await auto_messages.schedule_telegram_messages()
    stickers.schedule_sticker_cache_warmup(reason="startup")
    startup_state.set("telegram", "running", "Telegram підключено. Оновлюємо групи…")
    sync_db = SessionLocal()
    try:
        result = await groups.sync_telegram_groups(sync_db)
    finally:
        sync_db.close()
    log_event("INFO", "Groups", f"Автосинхронізація груп Telegram: додано {result.get('added_count', 0)}, оновлено назв {result.get('updated_count', 0)}")
    startup_state.set("telegram", "done", "Telegram підключено, групи оновлено")


async def _startup_logika():
    db = SessionLocal()
    try:
        config = db.query(LogikaSettings).first()
        if not config or not config.login or not config.password:
            startup_state.set("logika", "skipped", "Logika не підключена")
            return
        if not config.auto_sync_enabled:
            startup_state.set("logika", "skipped", "Автосинхронізація Logika вимкнена")
            return
        startup_state.set("logika", "running", "Синхронізуємо групи та розклад Logika…")
        result = await logika.sync_schedule(db=db)
        startup_state.set("logika", "done", f"Logika: оновлено {result['updated']}, додано {result['added']} груп")
    finally:
        db.close()


async def _run_startup_service(key, work, timeout):
    from logger import log_event
    try:
        await asyncio.wait_for(work(), timeout=timeout)
    except asyncio.CancelledError:
        startup_state.set(key, "skipped", "Оновлення зупинено")
        raise
    except Exception as error:
        name = "Telegram" if key == "telegram" else "Logika"
        startup_state.set(key, "error", f"{name}: не вдалося оновити. Збережені дані доступні; деталі в журналі")
        log_event("ERROR", name, f"Фоновий запуск: {error or 'перевищено час очікування'}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_state.reset()
    startup_state.set("server", "running", "Перевіряємо локальну базу даних…")
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations()
    from services.planner.schema import ensure_planner_migrations
    ensure_planner_migrations(engine)

    startup_state.set("server", "running", "Готуємо нагадування та локальний розклад…")
    try:
        auto_messages.scheduler.start()
    except Exception:
        pass
    parents_report.init_scheduler(auto_messages.scheduler)
    from services.planner.reminders import init_scheduler as init_planner_scheduler
    init_planner_scheduler(auto_messages.scheduler)
    db = SessionLocal()
    try:
        auto_messages.init_scheduler(db)
    finally:
        db.close()

    # Network work starts independently; HTTP readiness never waits for integrations.
    background = [
        asyncio.create_task(_run_startup_service("telegram", _startup_telegram, 90)),
        asyncio.create_task(_run_startup_service("logika", _startup_logika, 180)),
    ]
    app.state.startup_tasks = background
    startup_state.set("server", "done", "Локальні дані готові. Завантажуємо інтерфейс…")
    try:
        yield
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await settings.stop_session_restore()
        await planner_google.oauth.stop()
        try:
            auto_messages.scheduler.shutdown()
        except Exception:
            pass
        stickers.cancel_sticker_cache_warmup()
        try:
            await pyrogram_manager.disconnect()
        finally:
            engine.dispose()


# Створюємо FastAPI додаток
app = FastAPI(
    title="Менеджер Телеграм Груп",
    description="Веб-додаток для керування навчальним процесом (Pyrogram)",
    version="2.11.0",
    lifespan=lifespan
)

# Налаштування CORS для фронтенду
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_LOCAL_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_cross_origin_state_changes(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        origin
        and origin not in ALLOWED_LOCAL_ORIGINS
        and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
    ):
        return JSONResponse(status_code=403, content={"detail": "Forbidden origin"})
    return await call_next(request)

# Підключаємо роутери під префіксом /api
app.include_router(groups.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(auto_messages.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(stickers.router, prefix="/api")
app.include_router(parents_report.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(logika.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(planner_google.router, prefix="/api")


import traceback
from logger import log_event

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    error_type = type(exc).__name__
    trace = traceback.format_exc()
    log_event("ERROR", "System", f"Помилка сервера при {request.method} {request.url.path}: {error_type}: {error_msg}")
    print(f"[Unhandled Server Error] {request.method} {request.url.path}:\n{trace}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Внутрішня помилка сервера: {error_msg or error_type}"}
    )

# Роздача статичних файлів (Frontend)
import sys
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

dist_new = os.path.join(base_path, "frontend", "dist-new")
FRONTEND_DIST = dist_new if os.path.isdir(dist_new) and os.path.isfile(os.path.join(dist_new, "index.html")) else os.path.join(base_path, "frontend", "dist")

@app.get("/api/startup")
async def startup_progress():
    return startup_state.snapshot()


@app.get("/health")
def health_check():
    """Перевірка стану серверу"""
    return {
        "status": "ok",
        "pyrogram_connected": pyrogram_manager.is_connected
    }

if os.path.exists(FRONTEND_DIST):
    # Спочатку assets (CSS, JS)
    assets_path = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
        
    # Vite генерує favicon іноді в корінь
    @app.get("/vite.svg")
    def get_vite_svg():
        path = os.path.join(FRONTEND_DIST, "vite.svg")
        return FileResponse(path) if os.path.exists(path) else {"error": "Not found"}

    # Catch-all для SPA роутингу
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str, request: Request):
        # Якщо це API запит, але він сюди потрапив, значить 404
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        static_path = os.path.abspath(os.path.join(FRONTEND_DIST, full_path))
        frontend_root = os.path.abspath(FRONTEND_DIST)
        if (
            os.path.commonpath([frontend_root, static_path]) == frontend_root
            and os.path.isfile(static_path)
        ):
            return FileResponse(static_path)

        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built. Run npm run build"}
else:
    @app.get("/")
    def root():
        return {
            "message": "Менеджер Телеграм Груп API v2.11 (Pyrogram)",
            "docs": "/docs",
            "warning": "Фронтенд не знайдено (немає папки dist)"
        }
