"""Real launcher/HTTP UI with an isolated database and simulated slow integrations.

python tests/startup_preview.py --desktop --delay 45 [--offline]
No user sessions, real messages, or real external integrations are used.
"""
import argparse
import asyncio
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
parser = argparse.ArgumentParser()
parser.add_argument("--desktop", action="store_true")
parser.add_argument("--offline", action="store_true")
parser.add_argument("--delay", type=float, default=15)
parser.add_argument("--local-delay", type=float, default=0)
parser.add_argument("--port", type=int, default=8012)
parser.add_argument("--data-dir", type=Path, help="Keep the isolated preview.db here between test launches")
args = parser.parse_args()

import database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
tmp = None if args.data_dir else tempfile.TemporaryDirectory(prefix="school-manager-startup-")
preview_dir = args.data_dir.resolve() if args.data_dir else Path(tmp.name)
preview_dir.mkdir(parents=True, exist_ok=True)
database.engine = create_engine(f"sqlite:///{preview_dir / 'preview.db'}", connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(bind=database.engine, autoflush=False)
import main
main.ALLOWED_LOCAL_ORIGINS.add(f"http://127.0.0.1:{args.port}")
from models import Base, BotSettings, LogikaSettings
Base.metadata.create_all(database.engine)
with database.SessionLocal() as db:
    if not db.query(BotSettings).first():
        db.add(BotSettings())
    if not db.query(LogikaSettings).first():
        db.add(LogikaSettings(login="preview", password="preview", access_token="preview", teacher_id=22, auto_sync_enabled=1))
    db.commit()

manager = main.pyrogram_manager
manager.has_session = lambda: True
manager.get_user_info = AsyncMock(return_value={"name": "Тест запуску", "id": 1})
manager.disconnect = AsyncMock()
async def connect(*_args):
    await asyncio.sleep(args.delay)
    if args.offline:
        raise OSError("Preview: network offline")
    manager._is_connected = True
    return True
manager.connect_with_session = connect
main.groups.sync_telegram_groups = AsyncMock(return_value={"added_count": 0, "updated_count": 0})
main.auto_messages.schedule_telegram_messages = AsyncMock()
main.stickers.schedule_sticker_cache_warmup = Mock()
main.settings.schedule_sticker_cache_warmup = Mock()
main.parents_report.init_scheduler = Mock()
import services.planner.reminders
services.planner.reminders.init_scheduler = Mock()
main.system.check_update = AsyncMock(return_value={"update_available": False})

from logika_client import LogikaClient
def slow_schedule(self, **_kwargs):
    deadline = time.monotonic() + args.delay
    while time.monotonic() < deadline:
        self._check_cancelled()
        time.sleep(0.1)
    if args.offline:
        raise OSError("Preview: network offline")
    return []
LogikaClient.get_schedule = slow_schedule

import uvicorn
if args.desktop:
    import desktop_app
    create_window = desktop_app.webview.create_window
    def preview_window(title, *values, **kwargs):
        return create_window("ТЕСТ · School Manager", *values, **kwargs)
    desktop_app.webview.create_window = preview_window
    migrations = main.ensure_schema_migrations
    def slow_migrations():
        time.sleep(args.local_delay)
        migrations()
    main.ensure_schema_migrations = slow_migrations
    desktop_app.LAUNCHER_LOG = str(ROOT / "tmp/startup-preview-launcher.log")
    desktop_app.ERROR_LOG = str(ROOT / "tmp/startup-preview-error.log")
    desktop_app.CANDIDATE_URLS = [f"http://127.0.0.1:{args.port}"]
    desktop_app.kill_process_on_port = lambda _port: None
    desktop_app.run_tray = lambda: None
    config = uvicorn.Config
    def preview_config(*values, **kwargs):
        kwargs["port"] = args.port
        return config(*values, **kwargs)
    uvicorn.Config = preview_config
    desktop_app.main()
else:
    uvicorn.run(main.app, host="127.0.0.1", port=args.port)
