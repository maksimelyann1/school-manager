"""Opt-in live regression matrix, restricted to two explicitly authorized chats."""
import argparse
import asyncio
from contextlib import ExitStack, closing
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import HTTPException
from pyrogram import Client, raw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import logger
from models import Base, Group, ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import parents_report as reports
from telegram_credentials import get_default_credentials

TARGETS = {-5207171753: "тест 3", -1003235868709: "тест канал 4"}
SCENARIOS = {
    "normal": "Звичайне відправлення",
    "lost_ack": "Відповідь загубилася після доставки",
    "restart": "Усі відповіді загубилися, перевірка після перезапуску",
    "concurrent": "Одночасний ручний та автоматичний запуск",
    "post_send_error": "Помилка створення нагадування після доставки",
}


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def safe_root(value):
    root = Path(value).resolve()
    assert root.parent == (ROOT / "tmp").resolve() and root.name.startswith("report-matrix-")
    return root


class TestClient:
    def __init__(self, client, batch):
        self.client = client
        self.batch = batch
        self.mode = "normal"
        self.history_offline = False
        self.calls = []
        self.attempts = {}

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def invoke(self, request, **kwargs):
        assert isinstance(request, raw.functions.messages.SendMessage)
        peer = request.peer
        peer_id = -peer.chat_id if isinstance(peer, raw.types.InputPeerChat) else -(1000000000000 + peer.channel_id)
        assert peer_id in TARGETS and self.batch in request.message
        assert len(self.calls) < 40, "Live send safety limit reached"
        self.calls.append({"chat": peer_id, "random_id": str(request.random_id)})
        self.attempts[request.random_id] = self.attempts.get(request.random_id, 0) + 1
        response = await self.client.invoke(request, **kwargs)
        if self.mode == "restart" or (self.mode == "lost_ack" and self.attempts[request.random_id] == 1):
            raise TimeoutError("TEST: acknowledgement lost AFTER actual Telegram acceptance")
        return response

    async def get_chat_history(self, *args, **kwargs):
        if self.history_offline:
            raise ConnectionError("TEST: history temporarily unavailable")
        async for message in self.client.get_chat_history(*args, **kwargs):
            yield message


def snapshot(sessions):
    with sessions() as db:
        settings = db.query(ParentReportSettings).one()
        rows = []
        for lesson in db.query(ParentReportLesson).all():
            run = db.query(ParentReportRun).filter_by(lesson_id=lesson.id).one()
            rows.append({"marker": lesson.group_name, "lesson_id": lesson.id, "status": run.status,
                         "message_id": run.telegram_message_id, "lesson_count": lesson.lesson_count,
                         "last_report_date": lesson.last_report_date,
                         "telegram_id": run.telegram_chat_id, "random_id": run.telegram_random_id})
        return {"rows": rows, "pending_count": len(reports._collect_pending(db, settings))}


async def verify_history(client, sessions, batch):
    state = snapshot(sessions)
    found = {}
    for chat_id in TARGETS:
        messages = []
        async for msg in client.get_chat_history(chat_id, limit=100):
            text = str(msg.text or msg.caption or "")
            if batch in text:
                messages.append((msg.id, text))
        for row in state["rows"]:
            if row["telegram_id"] != str(chat_id):
                continue
            ids = [message_id for message_id, text in messages if row["marker"] in text]
            found[row["marker"]] = ids
            assert len(ids) == 1, f"Message count mismatch: {row['marker']}: {ids}"
            assert row["status"] == "success", f"Unconfirmed: {row}"
            assert row["message_id"] == ids[0], f"Wrong receipt: {row} / {ids}"
            assert row["lesson_count"] == "9" and row["last_report_date"], row
    assert state["pending_count"] == 0, state
    return {**state, "history": found}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-to-authorized-chats", action="store_true")
    parser.add_argument("--reopen")
    args = parser.parse_args()
    if args.reopen:
        root = safe_root(args.reopen)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        batch = manifest["batch"]
    else:
        assert args.send_to_authorized_chats, "Explicit live-test opt-in required"
        batch = "SM-MATRIX-" + uuid.uuid4().hex[:8]
        root = ROOT / "tmp" / ("report-matrix-" + batch[-8:])
        root.mkdir(parents=True)
        source_path = Path(os.environ["LOCALAPPDATA"]) / "SchoolManager" / "user_session.session"
        with closing(sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(root / "test_session.session")) as target:
                source.backup(target)
        (root / "manifest.json").write_text(json.dumps({"batch": batch}), encoding="utf-8")

    credentials = get_default_credentials()
    client = Client(str(root / "test_session"), api_id=credentials.api_id,
                    api_hash=credentials.api_hash, no_updates=True)
    engine = create_engine(f"sqlite:///{root / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    proxy = TestClient(client, batch)
    stack = ExitStack()
    stack.enter_context(patch.object(logger, "SessionLocal", sessions))
    stack.enter_context(patch.object(reports, "SessionLocal", sessions))
    stack.enter_context(patch.object(reports, "pyrogram_manager", SimpleNamespace(is_connected=True, client=proxy)))
    stack.enter_context(patch.object(reports, "_refresh_lesson_from_source", AsyncMock()))

    async def generate(settings, lesson, *args, **kwargs):
        return f"ТЕСТ автозвіту [{lesson.group_name}]\n{lesson.lesson_title}.\nЦе тестове повідомлення має з'явитися рівно один раз."

    stack.enter_context(patch.object(reports, "_generate_ai_report", generate))
    try:
        assert await asyncio.wait_for(client.connect(), 30), "Session is not authorized"
        for chat_id, name in TARGETS.items():
            chat = await asyncio.wait_for(client.get_chat(chat_id), 30)
            assert chat.title.strip().casefold() == name, f"Unexpected chat: {chat.title}"
            emit({"verified_chat": chat.title, "type": str(chat.type)})

        if args.reopen:
            with sessions() as db:
                await reports.reconcile_report_deliveries(db, force=True)
            for _ in range(10):
                await reports.process_auto_reports()
            assert not proxy.calls, "Restart attempted another send"
            result = await verify_history(client, sessions, batch)
            result["new_process"] = True
            (root / "restart-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            emit({"new_process_verified": True, "lessons": len(result["rows"]), "new_send_calls": len(proxy.calls)})
            return

        with sessions() as db:
            db.add(ParentReportSettings(auto_reports_enabled=1, google_ai_api_key="test-only",
                                       absent_followup_enabled=0, report_delay_minutes=0))
            for chat_id, name in TARGETS.items():
                db.add(Group(name=name, telegram_id=str(chat_id)))
            db.commit()

        results = []
        for chat_id, name in TARGETS.items():
            for mode, title in SCENARIOS.items():
                proxy.mode = mode
                proxy.history_offline = mode == "restart"
                marker = f"{batch}:{abs(chat_id)}:{mode}"
                with sessions() as db:
                    group = db.query(Group).filter_by(telegram_id=str(chat_id)).one()
                    start = datetime.now(reports.KYIV_TZ) - timedelta(hours=2)
                    lesson = ParentReportLesson(group_name=marker, telegram_group_id=group.id,
                        day=list(reports.WEEKDAY_MAP)[start.weekday()], start_time=start.strftime("%H:%M"),
                        duration_minutes=1, lesson_count="8", course="Тест", lesson_title=title)
                    db.add(lesson); db.commit()
                    lesson_id = lesson.id

                before = len(proxy.calls)
                if mode == "concurrent":
                    async def manual():
                        with sessions() as db:
                            try:
                                return await reports._send_lesson_report(db, db.get(ParentReportLesson, lesson_id),
                                    db.query(ParentReportSettings).one(), None, "", False, False)
                            except HTTPException as error:
                                assert error.status_code == 409
                    await asyncio.gather(reports.process_auto_reports(), reports.process_auto_reports(), manual())
                elif mode == "post_send_error":
                    with patch.object(reports, "_create_report_followup_auto_message", side_effect=RuntimeError("TEST: follow-up failed")), \
                         patch.object(reports, "_refresh_lesson_from_source", AsyncMock(side_effect=RuntimeError("TEST: course refresh failed"))):
                        await reports.process_auto_reports()
                else:
                    await reports.process_auto_reports()

                after_initial = len(proxy.calls)
                for _ in range(10):
                    await reports.process_auto_reports()
                assert len(proxy.calls) == after_initial, "Scheduler resent a report"
                if mode == "restart":
                    with sessions() as db:
                        run = db.query(ParentReportRun).filter_by(lesson_id=lesson_id).one()
                        assert run.status == "uncertain", run.status
                    proxy.history_offline = False
                    # Re-open a persisted DB and repeat confirmation; full process restart follows below.
                    with sessions() as db:
                        await reports.reconcile_report_deliveries(db, force=True)
                row = next(row for row in snapshot(sessions)["rows"] if row["lesson_id"] == lesson_id)
                assert row["status"] == "success", row
                result = {"chat": name, "scenario": mode, "send_attempts": after_initial - before,
                          "ticks_without_resend": 10, **row}
                results.append(result)
                emit({"scenario_passed": result})

        proxy.mode = "normal"
        before_timed = len(proxy.calls)
        scheduler = AsyncIOScheduler()
        ticks = 0
        async def tick():
            nonlocal ticks
            await reports.process_auto_reports()
            ticks += 1
            emit({"real_scheduler_tick": ticks, "new_send_calls": len(proxy.calls) - before_timed})
        scheduler.add_job(tick, "interval", seconds=60, max_instances=1)
        scheduler.start()
        try:
            async with asyncio.timeout(160):
                while ticks < 2:
                    await asyncio.sleep(1)
        finally:
            scheduler.shutdown(wait=False)
        assert len(proxy.calls) == before_timed, "Timed scheduler resent a report"
        state = await verify_history(client, sessions, batch)
        state.update({"batch": batch, "scenarios": results, "real_scheduler_ticks": ticks,
                      "send_calls": len(proxy.calls), "unique_random_ids": len(proxy.attempts)})
        (root / "result.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        emit({"matrix_passed": True, "messages": len(state["rows"]), "result_path": str(root / "result.json")})
    finally:
        if client.is_connected:
            await client.disconnect()
        stack.close()
        engine.dispose()
        if not args.reopen and sys.exc_info()[0] is not None:
            for path in root.glob("test_session.session*"):
                path.unlink()

    # A second Python process verifies persisted success after a genuine process restart.
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--reopen", str(root)], timeout=90)
    try:
        assert result.returncode == 0, "Restart verification failed"
    finally:
        for path in root.glob("test_session.session*"):
            path.unlink()


if __name__ == "__main__":
    asyncio.run(main())
