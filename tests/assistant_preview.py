"""Isolated HTTP fixture; no main app lifespan, integrations or schedulers."""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from database import Base, get_db
from models import BotSettings, ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import assistant, tasks, parents_report, groups, templates, categories, auto_messages, messages, files, settings, logs
import file_storage
import logger
from routers.parents_report import KYIV_TZ


def serve(port):
    with tempfile.TemporaryDirectory(prefix="mcp-fixture-", dir=ROOT / "tmp") as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'fixture.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False)
        # Every persistence and media operation in this process uses this fixture only.
        for module in (logger, settings, parents_report, auto_messages):
            module.SessionLocal = sessions
        for attribute, folder in (("TEMPLATE_FILES_DIR", "templates"), ("AUTO_MESSAGE_FILES_DIR", "auto"),
                                  ("PLANNER_FILES_DIR", "planner"), ("IMPORT_CACHE_DIR", "imports")):
            target = Path(directory) / folder
            target.mkdir()
            setattr(file_storage, attribute, str(target))
        fake_telegram = SimpleNamespace(is_connected=True, client=SimpleNamespace())
        messages.pyrogram_manager = fake_telegram
        parents_report.pyrogram_manager = fake_telegram
        # Network delivery/AI are replaced at service boundaries, not in the routes.
        messages.send_pyrogram_message = AsyncMock(return_value={"ok": True, "message_id": 100})
        parents_report.send_report_message = AsyncMock(return_value={"ok": True, "message_id": 200})
        parents_report._generate_ai_report = AsyncMock(return_value="Тестовий звіт без реального AI")
        parents_report.reconcile_report_deliveries = AsyncMock()
        parents_report.show_system_notification = Mock(return_value=False)
        auto_messages.show_system_notification = Mock(return_value=False)
        app = FastAPI()
        for router in (assistant.router, tasks.router, parents_report.router, groups.router,
                       templates.router, categories.router, auto_messages.router, messages.router,
                       files.router, settings.router, logs.router):
            app.include_router(router, prefix="/api")

        def override():
            with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override

        @app.get("/health")
        def health():
            return {"status": "ok", "pyrogram_connected": False, "fixture": True}

        @app.get("/api/system/notifications")
        def notifications():
            return {"enabled": False, "supported": True, "fixture": True}

        @app.post("/__test__/shutdown")
        def shutdown():
            server.should_exit = True
            return {"ok": True}

        @app.get("/__test__/evidence")
        def evidence():
            return {"simulated_message_sends": messages.send_pyrogram_message.await_count,
                    "simulated_report_sends": parents_report.send_report_message.await_count,
                    "simulated_ai_calls": parents_report._generate_ai_report.await_count,
                    "scheduler_running": auto_messages.scheduler.running,
                    "real_messages_sent": 0}

        now = datetime.now(KYIV_TZ) - timedelta(days=1)
        day = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "НД"][now.weekday()]
        with sessions() as db:
            db.add(BotSettings(windows_notifications_enabled=0))
            db.add(ParentReportSettings(default_duration_minutes=1, report_delay_minutes=0,
                absent_followup_enabled=0, report_notifications_enabled=0, auto_reports_enabled=0))
            for label, status in (("Доставлено", "success"), ("Без звіту", None),
                                  ("Помилка", "error"), ("Непідтверджено", "uncertain"),
                                  ("Ручна перевірка", "manual_required")):
                row = ParentReportLesson(group_name=label, day=day, start_time="00:00", duration_minutes=1)
                db.add(row)
                db.flush()
                if status:
                    db.add(ParentReportRun(lesson_id=row.id, lesson_group_name=label,
                        lesson_date=now.date().isoformat(), status=status, created_at=now.isoformat(),
                        telegram_message_id=42 if status == "success" else None,
                        error="Forbidden" if status == "error" else None))
            db.commit()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        try:
            server.run()
        finally:
            auto_messages.scheduler.remove_all_jobs()
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    serve(parser.parse_args().port)
