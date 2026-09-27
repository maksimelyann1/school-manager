"""Explicit opt-in live regression; sends only to an allowlisted test chat."""
import argparse
import asyncio
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pyrogram import Client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
import logger
from models import Group, ParentReportLesson, ParentReportRun, ParentReportSettings
from report_delivery import find_delivered_report
from routers import parents_report as reports
from telegram_credentials import get_default_credentials


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-to-test-chat", action="store_true", required=True)
    parser.parse_args()
    root = ROOT / "tmp" / f"delivery-live-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    data_dir = Path(os.environ["LOCALAPPDATA"]) / "SchoolManager"
    session_path = root / "test_session.session"
    source = sqlite3.connect(f"file:{data_dir / 'user_session.session'}?mode=ro", uri=True)
    target = sqlite3.connect(session_path)
    source.backup(target)
    source.close()
    target.close()
    credentials = get_default_credentials()
    client = Client(str(session_path.with_suffix("")), api_id=credentials.api_id,
                    api_hash=credentials.api_hash, no_updates=True)
    engine = create_engine(f"sqlite:///{root / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    logger.SessionLocal = sessions
    try:
        assert await asyncio.wait_for(client.connect(), 30), "Saved session is not authorized"
        chat_id = -5207171753
        chat = await asyncio.wait_for(client.get_chat(chat_id), 30)
        assert chat.title.strip().casefold() == "тест 3", "Test chat title does not match allowlist"
        print(json.dumps({"test_chat": chat.title, "chat_id": chat_id}), flush=True)
        marker = f"SM-DELIVERY-{uuid.uuid4().hex[:10]}"
        message = f"ТЕСТ виправлення автозвітів [{marker}]\nПеревірка втрати підтвердження Telegram: це повідомлення має з'явитися лише один раз."
        now = datetime.now(reports.KYIV_TZ)
        start = now - timedelta(hours=2)
        with sessions() as db:
            settings = ParentReportSettings(auto_reports_enabled=1, google_ai_api_key="test-only",
                                             absent_followup_enabled=0, report_delay_minutes=0)
            group = Group(name=chat.title, telegram_id=str(chat_id))
            db.add_all([settings, group]); db.flush()
            lesson = ParentReportLesson(group_name=marker, telegram_group_id=group.id,
                                         day=list(reports.WEEKDAY_MAP)[start.weekday()],
                                         start_time=start.strftime("%H:%M"), duration_minutes=1,
                                         lesson_count="8", course="Test course")
            db.add(lesson); db.commit()
            lesson_id = lesson.id

        class LostAckClient:
            def __init__(self):
                self.calls = 0
                self.ids = []
            def __getattr__(self, name):
                return getattr(client, name)
            async def invoke(self, request, **kwargs):
                assert request.peer.chat_id == abs(chat_id)
                self.calls += 1
                self.ids.append(request.random_id)
                result = await client.invoke(request, **kwargs)
                if self.calls == 1:
                    raise TimeoutError("Simulated lost acknowledgement AFTER Telegram accepted message")
                return result

        proxy = LostAckClient()
        with patch.object(reports, "SessionLocal", sessions), \
             patch.object(reports, "pyrogram_manager", SimpleNamespace(is_connected=True, client=proxy)), \
             patch.object(reports, "_generate_ai_report", AsyncMock(return_value=message)), \
             patch.object(reports, "_refresh_lesson_from_source", AsyncMock()):
            await reports.process_auto_reports()
            # Separate sessions simulate subsequent scheduler ticks and reopening the DB.
            for _ in range(5):
                await reports.process_auto_reports()
            with sessions() as db:
                row = db.get(ParentReportLesson, lesson_id)
                run = db.query(ParentReportRun).one()
                pending = reports._collect_pending(db, db.query(ParentReportSettings).one())
                assert run.status == "success", run.error
                assert row.lesson_count == "9"
                assert row.last_report_date
                assert not pending
                state = {"status": run.status, "message_id": run.telegram_message_id,
                         "last_report_date": row.last_report_date, "lesson_count": row.lesson_count,
                         "pending_count": len(pending), "send_calls": proxy.calls,
                         "unique_random_ids": len(set(proxy.ids))}
        found = []
        async for msg in client.get_chat_history(chat_id, limit=30):
            if marker in str(msg.text or ""):
                found.append(msg.id)
        assert len(found) == 1, f"Expected one message; got {found}"
        state["telegram_message_count"] = len(found)
        state["marker"] = marker

        (root / "result.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"result_path": str(root / 'result.json'), **state}, ensure_ascii=False), flush=True)
    finally:
        if client.is_connected:
            await client.disconnect()
        engine.dispose()
        for path in root.glob("test_session.session*"):
            path.unlink()


if __name__ == "__main__":
    asyncio.run(main())
