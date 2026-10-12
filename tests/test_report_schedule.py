"""Postponement and pause scheduling, without network access or user data."""
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import database
from models import Base, Group, ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import dashboard, logika, parents_report as reports


class ReportScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()
        self.settings = ParentReportSettings(auto_reports_enabled=1, google_ai_api_key="fake",
                                             absent_followup_enabled=0, report_delay_minutes=10,
                                             default_duration_minutes=90)
        self.group = Group(name="Тест", telegram_id="-123")
        self.db.add_all([self.settings, self.group])
        self.db.flush()
        self.lesson = ParentReportLesson(group_name="Перенесена група", telegram_group_id=self.group.id,
                                         day="ЧТ", start_time="16:00", course="Курс користувача",
                                         lesson_code="М5У1", lesson_count="17", absents="Учень",
                                         postponed_start_at="2026-11-01T16:00:00+02:00",
                                         postponed_from_date="2026-10-08")
        self.db.add(self.lesson)
        self.db.commit()
        self.now = datetime(2026, 10, 11, 16, tzinfo=reports.KYIV_TZ)
        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.now.astimezone(tz) if tz else owner.now.replace(tzinfo=None)

        self.stack = ExitStack()
        for module, name, value in [
            (reports, "SessionLocal", self.sessions), (reports, "datetime", Clock),
            (reports, "_today_kyiv", lambda: self.now.date()), (dashboard, "datetime", Clock),
            (reports, "pyrogram_manager", SimpleNamespace(is_connected=True, client=object())),
            (reports, "_report_send_lock", asyncio.Lock()), (logika, "_sync_lock", asyncio.Lock()),
            (reports, "log_event", lambda *args: None),
        ]:
            self.stack.enter_context(patch.object(module, name, value))
        self.send = self.stack.enter_context(patch.object(reports, "send_report_message", AsyncMock(
            return_value={"ok": True, "message_id": 123})))
        self.generate = self.stack.enter_context(patch.object(reports, "_generate_ai_report", AsyncMock(return_value="Звіт")))
        self.stack.enter_context(patch.object(reports, "_refresh_lesson_from_source", AsyncMock()))
        self.notify = self.stack.enter_context(patch.object(reports, "show_system_notification", return_value=True))

    def tearDown(self):
        self.stack.close()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def next_report(self):
        return dashboard.get_dashboard_stats(db=self.db)["reports_info"]["next_auto_report"]

    def pause(self, value):
        return reports.pause_schedule_row(self.lesson.id, reports.PauseLessonRequest(paused=value), db=self.db)

    async def test_future_postponement_is_used_by_dashboard_and_not_sent_early(self):
        self.assertEqual(self.next_report()["report_time"], "2026-11-01T17:40:00+02:00")
        self.assertEqual(reports._collect_pending(self.db, self.settings), [])
        await reports.process_auto_reports()
        self.send.assert_not_awaited()
        self.generate.assert_not_awaited()

    async def test_postponed_report_sends_once_after_new_end_and_delay(self):
        self.now = datetime(2026, 11, 1, 17, 39, tzinfo=reports.KYIV_TZ)
        await reports.process_auto_reports()
        self.send.assert_not_awaited()
        self.now += timedelta(minutes=1)
        self.assertEqual(self.next_report()["time_left"], "Очікує відправки")
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        self.send.assert_awaited_once()
        self.db.expire_all()
        self.assertIsNone(self.lesson.postponed_start_at)
        self.assertEqual(self.lesson.last_report_date, "01-11-2026")
        self.assertEqual(self.db.query(ParentReportRun).one().lesson_date, "2026-11-01")

    async def test_pause_excludes_pending_dashboard_and_auto_until_resumed(self):
        self.now = datetime(2026, 11, 1, 18, tzinfo=reports.KYIV_TZ)
        self.assertTrue(self.pause(True)["is_paused"])
        self.assertIsNone(self.next_report())
        self.assertEqual(reports._collect_pending(self.db, self.settings), [])
        await reports.process_auto_reports()
        self.send.assert_not_awaited()
        with self.sessions() as restarted:
            self.assertTrue(restarted.get(ParentReportLesson, self.lesson.id).is_paused)
        self.pause(False)
        await reports.process_auto_reports()
        self.send.assert_awaited_once()

    def test_pause_and_edit_preserve_user_settings_and_original_date(self):
        self.pause(True)
        payload = reports.PostponeLessonRequest(date="2026-11-08", time="18:30")
        result = reports.postpone_schedule_row(self.lesson.id, payload, db=self.db)
        self.assertTrue(result["is_paused"])
        self.assertEqual(result["postponed_start_at"], "2026-11-08T18:30:00+02:00")
        self.assertEqual(result["postponed_from_date"], "2026-10-08")
        self.assertEqual((self.lesson.day, self.lesson.start_time, self.lesson.course,
                          self.lesson.telegram_group_id, self.lesson.absents),
                         ("ЧТ", "16:00", "Курс користувача", self.group.id, "Учень"))
        reports.cancel_schedule_postpone(self.lesson.id, db=self.db)
        self.assertTrue(self.lesson.is_paused)
        self.assertIsNone(self.next_report())

    def test_resume_preserves_postponement_and_uses_its_time(self):
        self.pause(True)
        self.pause(False)
        self.assertEqual(self.next_report()["lesson_start"], "2026-11-01T16:00:00+02:00")

    async def test_pause_also_suppresses_pending_report_notifications(self):
        self.now = datetime(2026, 11, 1, 18, tzinfo=reports.KYIV_TZ)
        self.pause(True)
        await reports.process_report_system_notifications()
        self.notify.assert_not_called()

    def test_regular_report_uses_configured_duration_and_zero_delay(self):
        reports.cancel_schedule_postpone(self.lesson.id, db=self.db)
        self.settings.default_duration_minutes = 60
        self.settings.report_delay_minutes = 0
        self.db.commit()
        self.assertEqual(self.next_report()["report_time"], "2026-10-15T17:00:00+03:00")

    async def test_pending_selection_cannot_send_after_postponing_to_future(self):
        with self.assertRaises(HTTPException) as error:
            await reports._send_lesson_report(self.db, self.lesson, self.settings, None, None, True, False)
        self.assertEqual(error.exception.status_code, 409)
        self.send.assert_not_awaited()

    async def assert_change_during_generation_prevents_send(self, change):
        self.now = datetime(2026, 11, 1, 18, tzinfo=reports.KYIV_TZ)
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_ai(*args, **kwargs):
            entered.set()
            await release.wait()
            return "Звіт"
        self.generate.side_effect = slow_ai
        task = asyncio.create_task(reports._send_lesson_report(
            self.db, self.lesson, self.settings, None, None, True, False))
        await asyncio.wait_for(entered.wait(), timeout=2)
        with self.sessions() as other:
            change(other)
        release.set()
        with self.assertRaises(HTTPException) as error:
            await asyncio.wait_for(task, timeout=2)
        self.assertEqual(error.exception.status_code, 409)
        self.send.assert_not_awaited()
        self.assertEqual(self.db.query(ParentReportRun).count(), 0)

    async def test_pause_during_ai_stops_telegram_send(self):
        await self.assert_change_during_generation_prevents_send(lambda db: reports.pause_schedule_row(
            self.lesson.id, reports.PauseLessonRequest(paused=True), db=db))

    async def test_edit_postponement_during_ai_stops_old_report(self):
        await self.assert_change_during_generation_prevents_send(lambda db: reports.postpone_schedule_row(
            self.lesson.id, reports.PostponeLessonRequest(date="2026-11-08", time="16:00"), db=db))

    def test_unknown_group_pause_has_ukrainian_error(self):
        with self.assertRaises(HTTPException) as error:
            reports.pause_schedule_row(999, reports.PauseLessonRequest(paused=True), db=self.db)
        self.assertEqual((error.exception.status_code, error.exception.detail), (404, "Урок не знайдено"))


class PauseMigrationTests(unittest.TestCase):
    def test_old_database_gets_pause_default_without_losing_postponement(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        engine = create_engine(f"sqlite:///{temp.name}/old.db")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE parent_report_lessons (id INTEGER PRIMARY KEY, "
                                    "group_name VARCHAR, source_row INTEGER, postponed_start_at VARCHAR)"))
            connection.execute(text("INSERT INTO parent_report_lessons VALUES (1, 'Keep', 2, '2026-11-01T16:00:00+02:00')"))
        Base.metadata.create_all(engine)
        with patch.object(database, "engine", engine):
            database.ensure_schema_migrations()
            with engine.begin() as connection:
                self.assertEqual(connection.execute(text("SELECT is_paused FROM parent_report_lessons")).scalar(), 0)
                connection.execute(text("UPDATE parent_report_lessons SET is_paused = 1"))
            database.ensure_schema_migrations()
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text(
                "SELECT group_name, postponed_start_at, is_paused FROM parent_report_lessons")).one(),
                ("Keep", "2026-11-01T16:00:00+02:00", 1))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
