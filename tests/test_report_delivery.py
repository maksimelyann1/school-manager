import asyncio
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import HTTPException
from pyrogram import raw
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import database
from models import Base, Group, ParentReportLesson, ParentReportRun, ParentReportSettings
import report_delivery as delivery
import system_notifications
from routers import parents_report as reports


class ReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.settings = ParentReportSettings(auto_reports_enabled=1, google_ai_api_key="fake",
                                             absent_followup_enabled=0, report_delay_minutes=0)
        self.group = Group(name="test", telegram_id="-123")
        self.db.add_all([self.settings, self.group])
        self.db.flush()
        self.lesson = ParentReportLesson(group_name="Test lesson", telegram_group_id=self.group.id,
                                         day="ПН", start_time="00:01", duration_minutes=1,
                                         lesson_count="8", course="Frontend")
        self.db.add(self.lesson)
        self.db.commit()
        self.stack = ExitStack()
        for target, value in [
            ("SessionLocal", self.sessions),
            ("pyrogram_manager", SimpleNamespace(is_connected=True, client=object())),
            ("_report_send_lock", asyncio.Lock()),
            ("_today_kyiv", lambda: date(2026, 9, 28)),
            ("log_event", lambda *args: None),
        ]:
            self.stack.enter_context(patch.object(reports, target, value))
        self.send = self.stack.enter_context(patch.object(reports, "send_report_message", new_callable=AsyncMock))
        self.send.return_value = {"ok": True, "message_id": 321}
        self.find = self.stack.enter_context(patch.object(reports, "find_delivered_report", new_callable=AsyncMock))
        self.find.return_value = None
        self.refresh = self.stack.enter_context(patch.object(reports, "_refresh_lesson_from_source", new_callable=AsyncMock))
        self.notify = self.stack.enter_context(patch.object(reports, "show_system_notification", return_value=True))
        self.stack.enter_context(patch.object(reports, "_generate_ai_report", AsyncMock(return_value="Test report")))

    def tearDown(self):
        self.stack.close()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    async def send_report(self, db=None, is_test=False, is_auto=True):
        db = db or self.db
        return await reports._send_lesson_report(
            db, db.get(ParentReportLesson, self.lesson.id), db.get(ParentReportSettings, self.settings.id),
            "Test report", "Student", is_auto, is_test,
        )

    def assert_completed(self):
        self.db.expire_all()
        self.assertEqual(self.lesson.last_report_date, "28-09-2026")
        self.assertEqual(self.lesson.lesson_count, "9")
        self.assertEqual(self.db.query(ParentReportRun).one().status, "success")
        self.assertIsNone(reports._is_lesson_pending(
            self.db, self.lesson, self.settings, datetime(2026, 9, 28, 20, tzinfo=reports.KYIV_TZ),
        ))

    async def test_send_commits_and_second_attempt_is_blocked(self):
        await self.send_report()
        self.assert_completed()
        with self.assertRaises(HTTPException) as raised:
            await self.send_report()
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.send.await_count, 1)

    async def test_simultaneous_manual_and_auto_requests(self):
        async def slow_send(*args):
            await asyncio.sleep(0.02)
            return {"ok": True, "message_id": 321}
        self.send.side_effect = slow_send
        other = self.sessions()
        try:
            results = await asyncio.gather(self.send_report(), self.send_report(other), return_exceptions=True)
            self.assertEqual(sum(isinstance(result, HTTPException) for result in results), 1)
            self.assertEqual(self.send.await_count, 1)
            self.assert_completed()
        finally:
            other.close()

    async def test_lost_ack_reconciles_and_marks_success(self):
        self.send.return_value = {"ok": False, "uncertain": True, "description": "Request timed out"}
        self.find.return_value = 321
        await self.send_report()
        self.assert_completed()

    async def test_uncertain_delivery_survives_restart_and_never_resends(self):
        self.send.return_value = {"ok": False, "uncertain": True, "description": "Connection lost"}
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.assertEqual(self.db.query(ParentReportRun).one().status, "uncertain")
        for _ in range(5):
            await reports.process_auto_reports()
        restarted = self.sessions()
        try:
            with self.assertRaises(HTTPException):
                await self.send_report(restarted)
            self.find.return_value = 321
            await reports.reconcile_report_deliveries(restarted, force=True)
        finally:
            restarted.close()
        self.assertEqual(self.send.await_count, 1)
        self.assert_completed()

    async def test_crash_after_telegram_before_commit_recovers(self):
        with patch.object(reports, "_complete_report_delivery", side_effect=RuntimeError("disk error")):
            with self.assertRaises(RuntimeError):
                await self.send_report()
        self.db.rollback()
        self.assertEqual(self.db.query(ParentReportRun).one().status, "sending")
        self.find.return_value = 321
        await reports.reconcile_report_deliveries(self.db, force=True)
        self.assert_completed()
        self.assertEqual(self.send.await_count, 1)

    async def test_followup_and_source_failures_cannot_undo_delivery(self):
        self.refresh.side_effect = RuntimeError("Google offline")
        with patch.object(reports, "_create_report_followup_auto_message", side_effect=RuntimeError("followup failed")):
            await self.send_report()
        self.assert_completed()

    async def test_definite_rejection_can_retry(self):
        self.send.return_value = {"ok": False, "uncertain": False, "description": "CHAT_WRITE_FORBIDDEN"}
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.send.return_value = {"ok": True, "message_id": 321}
        await self.send_report()
        self.assert_completed()

    async def test_legacy_timeout_recovers_without_new_message(self):
        reports._record_report_run(self.db, self.lesson, date(2026, 9, 28), "error", "Test report",
                                   "Request timed out", self.group.id, "Student", True, False)
        self.db.commit()
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.find.return_value = 321
        await reports.reconcile_report_deliveries(self.db, force=True)
        self.assert_completed()
        self.send.assert_not_awaited()

    async def test_test_mode_does_not_close_real_lesson(self):
        await self.send_report(is_test=True)
        self.assertFalse(self.lesson.last_report_date)
        self.assertEqual(self.lesson.lesson_count, "8")

    async def test_database_claim_is_unique(self):
        await self.send_report()
        run = self.db.query(ParentReportRun).one()
        other = ParentReportRun(lesson_group_name="Other", lesson_date=run.lesson_date,
                                 status="sending", created_at=run.created_at, delivery_key=run.delivery_key)
        self.db.add(other)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    async def test_cleared_report_date_cannot_cause_resend(self):
        await self.send_report()
        self.lesson.last_report_date = ""
        self.db.commit()
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.assertEqual(self.send.await_count, 1)
        self.assertIsNone(reports._is_lesson_pending(
            self.db, self.lesson, self.settings, datetime(2026, 9, 28, 20, tzinfo=reports.KYIV_TZ),
        ))

    async def test_repeated_ack_does_not_increment_twice(self):
        await self.send_report()
        run = self.db.query(ParentReportRun).one()
        self.assertFalse(reports._complete_report_delivery(self.db, self.lesson, run, 321))
        self.assert_completed()

    async def test_notification_only_after_persisted_success_and_only_once(self):
        observed = []
        def show(title, message):
            with self.sessions() as persisted:
                observed.append((persisted.query(ParentReportRun).one().status,
                                 persisted.get(ParentReportLesson, self.lesson.id).lesson_count))
            return True
        self.notify.side_effect = show
        await self.send_report()
        for _ in range(3):
            await reports.process_auto_reports()
        reports._complete_report_delivery(self.db, self.lesson, self.db.query(ParentReportRun).one(), 321)
        self.notify.assert_called_once()
        self.assertEqual(observed, [("success", "9")])
        title, message = self.notify.call_args.args
        self.assertEqual(title, "Автозвіт відправлено")
        self.assertIn("test", message)
        self.assertIn("28-09-2026", message)

    async def test_uncertain_delivery_notifies_only_after_recovery(self):
        self.send.return_value = {"ok": False, "uncertain": True, "description": "Connection lost"}
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.notify.assert_not_called()
        self.find.return_value = 321
        await reports.reconcile_report_deliveries(self.db, force=True)
        await reports.reconcile_report_deliveries(self.db, force=True)
        self.notify.assert_called_once()
        self.assert_completed()

    async def test_report_notification_setting_is_respected(self):
        self.settings.report_notifications_enabled = 0
        self.db.commit()
        await self.send_report()
        self.notify.assert_not_called()
        self.assert_completed()

    async def test_manual_and_test_reports_do_not_show_auto_notification(self):
        await self.send_report(is_test=True)
        await self.send_report(is_auto=False)
        self.notify.assert_not_called()

    async def test_notification_failure_cannot_undo_delivery(self):
        self.notify.side_effect = RuntimeError("OS notification unavailable")
        await self.send_report()
        self.assert_completed()
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.send.assert_awaited_once()


class SystemNotificationRoutingTests(unittest.TestCase):
    def test_existing_windows_and_macos_adapters_and_global_setting(self):
        for platform, adapter in [("win32", "_show_windows_notification"), ("darwin", "_show_macos_notification")]:
            for enabled in [True, False]:
                with self.subTest(platform=platform, enabled=enabled), \
                     patch.object(system_notifications.sys, "platform", platform), \
                     patch.object(system_notifications, "_settings_enabled", return_value=enabled), \
                     patch.object(system_notifications, adapter, return_value=True) as native:
                    result = system_notifications.show_system_notification("Автозвіт відправлено", "test")
                    self.assertEqual(result, enabled)
                    if enabled:
                        native.assert_called_once_with("Автозвіт відправлено", "test")
                    else:
                        native.assert_not_called()


class TelegramTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_reuses_random_id_after_acceptance(self):
        requests = []
        accepted = set()
        async def invoke(request, **kwargs):
            requests.append(request)
            accepted.add(request.random_id)
            if len(requests) == 1:
                raise TimeoutError("Request timed out")
            return raw.types.UpdateShortSentMessage(id=42, pts=1, pts_count=1, date=1, out=True)
        client = SimpleNamespace(
            parser=SimpleNamespace(parse=AsyncMock(return_value={"message": "hello", "entities": None})),
            resolve_peer=AsyncMock(return_value=raw.types.InputPeerChat(chat_id=123)), invoke=invoke,
        )
        with patch("telegram_send_queue.log_event"), patch("telegram_send_queue._retry_delay", return_value=0):
            result = await delivery.send_report_message(client, "-123", "hello", "7654321", "test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message_id"], 42)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(accepted), 1)
        self.assertIs(requests[0], requests[1])

    async def test_history_ignores_other_senders_and_dates(self):
        now = datetime.now().astimezone()
        async def history(*args, **kwargs):
            for msg in [
                SimpleNamespace(id=9, date=now, outgoing=False, text="hello"),
                SimpleNamespace(id=8, date=now, outgoing=True, text="different"),
                SimpleNamespace(id=7, date=now, outgoing=True, text="hello"),
            ]:
                yield msg
        client = SimpleNamespace(parser=SimpleNamespace(parse=AsyncMock(return_value={"message": "hello", "entities": None})),
                                 get_chat_history=history)
        self.assertEqual(await delivery.find_delivered_report(client, "-123", "hello", now.isoformat()), 7)
        self.assertIsNone(await delivery.find_delivered_report(client, "-123", "hello", (now + timedelta(days=7)).isoformat()))


class MigrationTests(unittest.TestCase):
    def test_old_database_upgrade_is_repeatable_and_preserves_content(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE parent_report_runs (id INTEGER PRIMARY KEY, status VARCHAR)"))
            connection.execute(text("INSERT INTO parent_report_runs VALUES (1, 'success')"))
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO parent_report_courses (id,name,row_order) VALUES (1,'Course',0)"))
            connection.execute(text("INSERT INTO parent_report_course_lessons (id,course_id,course_name,lesson_count,lesson_report_text,source_row,row_order) VALUES (1,1,'Course',1,'Keep me',0,0)"))
        with patch.object(database, "engine", engine):
            database.ensure_schema_migrations()
            database.ensure_schema_migrations()
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT status FROM parent_report_runs")).scalar(), "success")
            self.assertEqual(connection.execute(text("SELECT lesson_report_text FROM parent_report_course_lessons")).scalar(), "Keep me")
            self.assertIn("telegram_random_id", {row[1] for row in connection.execute(text("PRAGMA table_info(parent_report_runs)"))})
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
