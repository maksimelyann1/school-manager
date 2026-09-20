# Головний файл FastAPI додатку
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import HTTPException
import os

from database import engine, Base, SessionLocal, ensure_schema_migrations
from models import Group, BotSettings, AutoMessage, Template, Category, LogikaSettings, ParentReportLesson
from routers import groups, settings, messages, auto_messages, templates, categories, logs, dashboard, files, stickers, parents_report, ai, logika
from routers import system
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Виконується при старті та зупинці додатку"""
    # Створюємо таблиці в базі даних
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations()
    
    # Запускаємо локальний планувальник
    try:
        auto_messages.scheduler.start()
    except Exception:
        pass  # Може бути вже запущений при reload
    parents_report.init_scheduler(auto_messages.scheduler)
    
    # Ініціалізуємо заплановані повідомлення в локальний планувальник
    db = SessionLocal()
    try:
        auto_messages.init_scheduler(db)
        
        # Спробуємо підключити Pyrogram якщо є збережена сесія
        db_settings = db.query(BotSettings).first()
        if db_settings and stored_credentials_match_default(db_settings):
            db_settings.api_id = None
            db_settings.api_hash = None
            db.commit()
            db.refresh(db_settings)
        try:
            credentials = get_effective_credentials(db_settings)
        except Exception as e:
            credentials = None
            print(f"[Main] Некоректні Telegram credentials: {e}")

        if credentials:
            try:
                connected = await pyrogram_manager.connect_with_session(
                    credentials.api_id,
                    credentials.api_hash
                )
                if connected:
                    # Плануємо відкладені повідомлення через Telegram
                    await auto_messages.schedule_telegram_messages()
                    stickers.schedule_sticker_cache_warmup(reason="startup")

                    # Автоматична синхронізація груп Telegram при старті (оновлює назви та додає нові)
                    async def _bg_startup_sync_groups():
                        import asyncio
                        await asyncio.sleep(2)  # Невелика пауза після старту
                        sync_db = SessionLocal()
                        try:
                            from logger import log_event
                            res = await groups.sync_telegram_groups(sync_db)
                            if res.get('added_count', 0) > 0 or res.get('updated_count', 0) > 0:
                                log_event("INFO", "Groups", f"Автосинхронізація груп Telegram: додано {res.get('added_count', 0)}, оновлено назв {res.get('updated_count', 0)}")
                        except Exception as sync_err:
                            print(f"[Main] Помилка фонової синхронізації Telegram груп: {sync_err}")
                        finally:
                            sync_db.close()

                    import asyncio
                    asyncio.create_task(_bg_startup_sync_groups())
                else:
                    print("[Main] Pyrogram сесія не знайдена або недійсна. Потрібна авторизація.")
            except Exception as e:
                print(f"[Main] Помилка підключення Pyrogram: {e}")
        else:
            print("[Main] API credentials не налаштовані. Перейдіть в Налаштування.")

        # Автоматична синхронізація розкладу Logika при старті, якщо увімкнено
        try:
            l_settings = db.query(LogikaSettings).first()
            if l_settings and l_settings.login and l_settings.password and l_settings.auto_sync_enabled:
                import asyncio
                from routers.logika import sync_schedule

                def _bg_sync():
                    sync_db = SessionLocal()
                    try:
                        sync_schedule(db=sync_db)
                    except Exception as err:
                        print(f"[Main] Помилка авто-синхронізації Logika: {err}")
                    finally:
                        sync_db.close()

                asyncio.create_task(asyncio.to_thread(_bg_sync))
        except Exception as e:
            print(f"[Main] Помилка перевірки автосинхронізації Logika: {e}")
    finally:
        db.close()
    
    yield
    
    # Зупиняємо планувальник
    try:
        auto_messages.scheduler.shutdown()
    except Exception:
        pass
    
    # Від'єднуємо Pyrogram
    stickers.cancel_sticker_cache_warmup()
    try:
        await pyrogram_manager.disconnect()
    finally:
        # Закриваємо SQLite-пул після планувальників і Telegram-клієнта.
        engine.dispose()


# Створюємо FastAPI додаток
app = FastAPI(
    title="Менеджер Телеграм Груп",
    description="Веб-додаток для керування навчальним процесом (Pyrogram)",
    version="2.6.0",
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
            "message": "Менеджер Телеграм Груп API v2.6 (Pyrogram)",
            "docs": "/docs",
            "warning": "Фронтенд не знайдено (немає папки dist)"
        }
