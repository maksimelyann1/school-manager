import asyncio
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from logika_client import LogikaClient, parse_attendance
from models import Base, Group, LogikaSettings, ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import logika, parents_report as reports


COURSE = "Фронтенд Н_П"
MATERIALS = {COURSE: [
    {"lesson_code": code, "lesson_count": number, "source_row": number + 1,
     "lesson_title": f"Назва {code}", "lesson_report_text": f"Матеріал {code}"}
    for code, number in [("М2У3", 7), ("М2У4", 8), ("М2У5", 9)]
]}


def platform_lesson(day=1, code="М2У5", schedule_id=101, hour=14, **changes):
    item = {
        "id": schedule_id, "group": {"key": 77, "value": "Нова назва у Logika"},
        "teacher": {"key": 22}, "groupStatus": "ACTIVE", "contentType": "GROUP", "lessonStatus": "FINISH",
        "start": f"2026-09-{day:02d}T{hour:02d}:00:00+03:00", "duration": 5400,
        "lesson": {"value": f"{code} Тема з платформи"},
    }
    item.update(changes)
    return item


def attendance(schedule_id=101, states=("PRESENT", "PRESENT")):
    return [{"studentId": {"key": index, "value": f"Учень {index}"},
             "scheduleId": schedule_id, "state": state}
            for index, state in enumerate(states, start=1)]


class LogikaReportSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.settings = ParentReportSettings(
            auto_reports_enabled=1, google_ai_api_key="fake", absent_followup_enabled=0,
            report_delay_minutes=10, report_notifications_enabled=0,
            prompt_template="{lesson_code}|{lesson_count}|{topic}|{absents}",
        )
        self.config = LogikaSettings(login="fake", password="fake", access_token="fake",
                                     teacher_id=22, auto_fetch_absents=0)
        self.group = Group(name="Telegram з іншою назвою", telegram_id="-123")
        self.db.add_all([self.settings, self.config, self.group])
        self.db.flush()
        self.lesson = ParentReportLesson(
            group_name="Стара назва групи", telegram_group_id=self.group.id, day="ВТ",
            start_time="14:00", duration_minutes=90, course=COURSE,
            lesson_code="М2У4", lesson_count="8", lesson_title="Назва М2У4",
            lesson_report_text="Матеріал М2У4", absents="Введено вручну",
            last_report_date="25-08-2026", logika_group_id=77, logika_schedule_id=999,
        )
        self.db.add(self.lesson)
        self.db.commit()
        self.today = date(2026, 9, 2)  # Report can be prepared the day after the lesson.
        self.now = datetime(2026, 9, 2, 20, tzinfo=reports.KYIV_TZ)
        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.now.astimezone(tz) if tz else owner.now.replace(tzinfo=None)

        self.stack = ExitStack()
        for target, value in [
            ("SessionLocal", self.sessions), ("_today_kyiv", lambda: self.today),
            ("datetime", Clock), ("_report_send_lock", asyncio.Lock()),
            ("_ai_report_lock", asyncio.Lock()),
            ("pyrogram_manager", SimpleNamespace(is_connected=True, client=object())),
        ]:
            self.stack.enter_context(patch.object(reports, target, value))
        self.stack.enter_context(patch.object(logika, "datetime", Clock))
        self.stack.enter_context(patch.object(logika, "_sync_lock", asyncio.Lock()))
        self.log = self.stack.enter_context(patch.object(reports, "log_event"))
        self.stack.enter_context(patch.object(logika, "log_event"))
        self.source = self.stack.enter_context(patch.object(
            reports, "_load_source_course_lessons", AsyncMock(return_value=MATERIALS)))
        self.client = Mock(access_token="fake", refresh_token=None, xsrf_token=None)
        self.client.get_group_schedule.return_value = [
            platform_lesson(8, "М2У4", 108), platform_lesson(1, "М2У5", 101),
        ]
        self.client.get_absent_students.return_value = []
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id)
        self.stack.enter_context(patch("logika_client.LogikaClient", return_value=self.client))
        self.stack.enter_context(patch.object(logika, "get_authenticated_client", return_value=self.client))
        self.ai = AsyncMock()
        self.ai.post.return_value = SimpleNamespace(status_code=200, json=lambda: {
            "candidates": [{"content": {"parts": [{"text": "Згенерований звіт"}]}}],
        })
        context = AsyncMock()
        context.__aenter__.return_value = self.ai
        self.stack.enter_context(patch.object(reports.httpx, "AsyncClient", return_value=context))
        self.send = self.stack.enter_context(patch.object(
            reports, "send_report_message", AsyncMock(return_value={"ok": True, "message_id": 42})))
        self.stack.enter_context(patch.object(reports, "find_delivered_report", AsyncMock(return_value=None)))
        self.stack.enter_context(patch.object(reports, "show_system_notification"))

    def tearDown(self):
        self.stack.close()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    async def sync(self, is_auto=True):
        await reports._sync_logika_lesson_before_report(
            self.db, self.lesson, reports._lesson_schedule_context(self.lesson, self.settings), is_auto=is_auto)

    async def send_report(self, is_auto=True):
        return await reports._send_lesson_report(
            self.db, self.lesson, self.settings, None, self.lesson.absents, is_auto, False)

    async def test_swapped_topics_on_two_dates_reach_ai_and_are_persisted_first(self):
        observed = []

        async def record_prompt(*args, **kwargs):
            with self.sessions() as read_db:
                stored = read_db.get(ParentReportLesson, self.lesson.id)
                observed.append((stored.lesson_code, stored.lesson_count, stored.lesson_report_text))
            return SimpleNamespace(status_code=200, json=lambda: {
                "candidates": [{"content": {"parts": [{"text": "Звіт " + observed[-1][0]}]}}],
            })

        self.ai.post.side_effect = record_prompt
        await self.send_report()
        self.today = date(2026, 9, 9)
        self.now += timedelta(days=7)
        await self.send_report()
        self.assertEqual(observed, [("М2У5", "9", "Матеріал М2У5"), ("М2У4", "8", "Матеріал М2У4")])
        prompts = [call.kwargs["json"]["contents"][0]["parts"][0]["text"] for call in self.ai.post.await_args_list]
        self.assertIn("М2У5|9|Матеріал М2У5", prompts[0])
        self.assertIn("М2У4|8|Матеріал М2У4", prompts[1])
        self.assertEqual(self.send.await_count, 2)
        self.assertEqual([r.lesson_date for r in self.db.query(ParentReportRun).order_by(ParentReportRun.id)],
                         ["2026-09-01", "2026-09-08"])
        self.client.get_absent_students.assert_not_called()

    async def test_same_code_repairs_stale_number_and_preserves_user_settings(self):
        self.client.get_group_schedule.return_value = [platform_lesson(code="М2У4")]
        self.lesson.lesson_count = "99"
        await self.sync()
        self.db.expire_all()
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count), ("М2У4", "8"))
        self.assertEqual((self.lesson.telegram_group_id, self.lesson.course, self.lesson.day,
                          self.lesson.start_time, self.lesson.last_report_date, self.lesson.absents),
                         (self.group.id, COURSE, "ВТ", "14:00", "25-08-2026", "Введено вручну"))

    async def test_manual_generation_also_syncs_and_preserves_absents(self):
        self.config.auto_fetch_absents = 1
        self.db.commit()
        await self.send_report(is_auto=False)
        self.assertIn("М2У5|9|Матеріал М2У5|Введено вручну",
                      self.ai.post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])
        self.client.get_attendance.assert_called_once_with(101)
        self.assertEqual(self.lesson.absents, "Введено вручну")
        self.client.get_absent_students.assert_not_called()

    async def test_attendance_uses_finished_schedule_id(self):
        self.config.auto_fetch_absents = 1
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "ABSENT", "PRESENT"))
        await self.sync()
        self.client.get_attendance.assert_called_once_with(101)
        self.assertEqual(self.lesson.absents, "Учень 2")

    async def test_new_individual_student_must_be_explicitly_present(self):
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="INDIVIDUAL", studentsAmount=1)]
        for state in ["ABSENT", "NO_LESSON", "MISSED"]:
            with self.subTest(state=state):
                self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, (state,))
                with self.assertRaises(HTTPException) as error:
                    await self.send_report()
                self.assertIn("єдиний учень", error.exception.detail)
                self.db.rollback()
                self.assertEqual(self.lesson.last_report_date, "25-08-2026")
                self.assertEqual(self.lesson.lesson_code, "М2У4")
                self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT",))
        await self.send_report()
        self.send.assert_awaited_once()

    async def test_group_with_one_student_also_requires_presence(self):
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="GROUP", studentsAmount=1)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT",))
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.send.assert_not_awaited()
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT",))
        await self.send_report()
        self.send.assert_awaited_once()

    async def test_skipped_report_keeps_refreshed_tokens_without_changing_lesson(self):
        self.client.access_token = "renewed"
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="INDIVIDUAL", studentsAmount=1)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT",))
        with self.assertRaises(HTTPException):
            await self.send_report()
        self.db.rollback()
        self.assertEqual(self.config.access_token, "renewed")
        self.assertEqual(self.lesson.lesson_code, "М2У4")
        self.assertEqual(self.lesson.last_report_date, "25-08-2026")

    async def test_partial_group_journal_is_not_mistaken_for_individual_attendance(self):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT",))
        with self.assertRaises(HTTPException) as error:
            await self.send_report()
        self.assertIn("повного журналу", error.exception.detail)
        self.send.assert_not_awaited()

    async def test_incomplete_wrong_or_conflicting_journal_never_sends(self):
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="INDIVIDUAL", studentsAmount=1)]
        cases = [[], {}, attendance(108, ("PRESENT",)), attendance(101),
                 [{"studentId": {"key": 1}, "state": "PRESENT"}],
                 [{"scheduleId": 101, "studentId": {}, "state": "PRESENT"}],
                 attendance(101, ("PRESENT",)) + attendance(101, ("ABSENT",))]
        self.client.get_attendance.side_effect = None
        for records in cases:
            with self.subTest(records=records):
                self.client.get_attendance.return_value = records
                with self.assertRaises(HTTPException):
                    await self.send_report()
                self.db.rollback()
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_attendance_outage_or_supplied_auto_text_cannot_bypass_presence(self):
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="INDIVIDUAL", studentsAmount=1)]
        self.client.get_attendance.side_effect = RuntimeError("Журнал недоступний")
        with self.assertRaises(HTTPException) as error:
            await self.send_report()
        self.assertEqual(error.exception.status_code, 502)
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("NO_LESSON",))
        with self.assertRaises(HTTPException):
            await reports._send_lesson_report(self.db, self.lesson, self.settings, "Готовий текст", "", True, False)
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_scheduler_waits_for_presence_and_then_sends_only_once(self):
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="INDIVIDUAL", studentsAmount=1)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT",))
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        self.send.assert_not_awaited()
        self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.assertTrue(any("єдиний учень" in str(call) for call in self.log.call_args_list))
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT",))
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        self.send.assert_awaited_once()

    async def test_pair_with_one_present_requires_manual_decision(self):
        self.config.auto_fetch_absents = 1
        self.db.commit()
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT", "PRESENT"))
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()
        run = self.db.query(ParentReportRun).one()
        self.assertEqual((run.status, run.lesson_date, run.absents),
                         ("manual_required", "2026-09-01", "Учень 1"))
        self.client.get_attendance.assert_called_once_with(101)
        with self.sessions() as restarted:
            item = reports._collect_pending(restarted, self.settings)[0]
            self.assertTrue(item["manual_required"])
            self.assertEqual((item["review_run_id"], item["lesson_code"]), (run.id, "М2У5"))

    async def make_manual_review(self):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "ABSENT"))
        await reports.process_auto_reports()
        self.db.expire_all()
        return self.db.query(ParentReportRun).one()

    async def test_manual_pair_preview_and_send_fetch_dated_absents_without_override(self):
        run = await self.make_manual_review()
        payload = reports.SendReportRequest(lesson_id=self.lesson.id, lesson_date="2026-09-01", review_run_id=run.id)
        preview = await reports.preview_manual_report(payload, self.db)
        self.assertEqual((preview["lesson_code"], preview["lesson_count"], preview["absents"]),
                         ("М2У5", "9", "Учень 2"))
        await reports.send_report(payload, self.db)
        self.send.assert_awaited_once()
        prompt = self.ai.post.await_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("М2У5|9|Матеріал М2У5|Учень 2", prompt)
        self.assertEqual(run.status, "success")
        self.assertEqual(reports._collect_pending(self.db, self.settings), [])
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count, self.lesson.last_report_date),
                         ("М2У4", "8", "01-09-2026"))
        with self.assertRaises(HTTPException):
            await reports.send_report(payload, self.db)
        self.send.assert_awaited_once()

    async def test_old_manual_review_survives_future_sync_and_newer_report(self):
        run = await self.make_manual_review()
        self.today, self.now = date(2026, 9, 16), self.now + timedelta(days=14)
        self.lesson.lesson_code, self.lesson.lesson_count = "М2У3", "7"
        self.lesson.logika_schedule_id = 115
        self.lesson.last_report_date = "15-09-2026"
        self.lesson.absents = "Для майбутнього уроку"
        self.db.commit()
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2),
                                                       platform_lesson(15, "М2У3", 115, studentsAmount=2)]
        pending = reports._collect_pending(self.db, self.settings)
        self.assertEqual(len(pending), 1)
        self.assertEqual((pending[0]["lesson_run_date"], pending[0]["lesson_code"]), ("2026-09-01", "М2У5"))
        self.client.get_attendance.reset_mock()
        await reports.send_report(reports.SendReportRequest(lesson_id=self.lesson.id,
                                  lesson_date="2026-09-01", review_run_id=run.id), self.db)
        self.client.get_attendance.assert_called_once_with(101)
        self.assertEqual(run.lesson_date, "2026-09-01")
        self.db.refresh(self.lesson)
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count, self.lesson.absents,
                          self.lesson.last_report_date, self.lesson.logika_schedule_id),
                         ("М2У3", "7", "Для майбутнього уроку", "15-09-2026", 115))
        self.assertEqual(reports._collect_pending(self.db, self.settings), [])

    async def test_two_dates_can_wait_for_separate_manual_decisions(self):
        run = await self.make_manual_review()
        self.today, self.now = date(2026, 9, 9), self.now + timedelta(days=7)
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2),
                                                       platform_lesson(8, "М2У4", 108, studentsAmount=2)]
        await reports.process_auto_reports()
        pending = reports._collect_pending(self.db, self.settings)
        self.assertEqual([(item["lesson_run_date"], item["lesson_code"]) for item in pending],
                         [("2026-09-01", "М2У5"), ("2026-09-08", "М2У4")])
        await reports.send_report(reports.SendReportRequest(lesson_id=self.lesson.id,
                                  lesson_date="2026-09-01", review_run_id=run.id), self.db)
        self.assertEqual([item["lesson_run_date"] for item in reports._collect_pending(self.db, self.settings)],
                         ["2026-09-08"])

    async def test_manual_override_and_explicit_empty_absents_are_preserved(self):
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "ABSENT"))
        for value in ("Введено вручну", ""):
            payload = reports.SendReportRequest(lesson_id=self.lesson.id, lesson_date="2026-09-01", absents=value, test=True)
            await reports.send_report(payload, self.db)
            self.assertEqual(self.db.query(ParentReportRun).order_by(ParentReportRun.id.desc()).first().absents, value)
            prompt = self.ai.post.await_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
            self.assertIn(f"Матеріал М2У5|{value}", prompt)

    async def test_unclear_attendance_is_manual_and_cannot_be_sent_until_corrected(self):
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "UNKNOWN"))
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        run = self.db.query(ParentReportRun).one()
        self.assertEqual(run.status, "manual_required")
        payload = reports.SendReportRequest(lesson_id=self.lesson.id, lesson_date="2026-09-01", review_run_id=run.id)
        with self.assertRaises(HTTPException):
            await reports.send_report(payload, self.db)
        self.send.assert_not_awaited()
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id)
        await reports.send_report(payload, self.db)
        self.send.assert_awaited_once()

    async def test_manual_pair_cannot_send_when_both_become_absent(self):
        run = await self.make_manual_review()
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT", "ABSENT"))
        with self.assertRaises(HTTPException):
            await reports.send_report(reports.SendReportRequest(lesson_id=self.lesson.id,
                                      review_run_id=run.id, absents=""), self.db)
        self.send.assert_not_awaited()
        self.assertEqual(run.status, "manual_required")

    async def test_manual_failure_keeps_dated_report_and_retry_sends_once(self):
        run = await self.make_manual_review()
        self.send.return_value = {"ok": False, "uncertain": False, "description": "Telegram відмовив"}
        payload = reports.SendReportRequest(lesson_id=self.lesson.id, lesson_date="2026-09-01", review_run_id=run.id)
        with self.assertRaises(HTTPException):
            await reports.send_report(payload, self.db)
        self.assertEqual(reports._collect_pending(self.db, self.settings)[0]["review_run_id"], run.id)
        await reports.process_auto_reports()
        self.assertEqual(self.send.await_count, 1)
        self.send.return_value = {"ok": True, "message_id": 42}
        await reports.send_report(payload, self.db)
        self.assertEqual(self.db.query(ParentReportRun).count(), 1)
        self.assertEqual(run.status, "success")

    async def test_network_failure_retains_auto_retry(self):
        self.client.get_group_schedule.side_effect = RuntimeError("Тимчасово немає мережі")
        await reports.process_auto_reports()
        self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.client.get_group_schedule.side_effect = None
        await reports.process_auto_reports()
        self.send.assert_awaited_once()

    async def test_incomplete_journal_creates_one_review_and_pause_keeps_it(self):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT",))
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        self.assertEqual(self.db.query(ParentReportRun).one().status, "manual_required")
        self.lesson.is_paused = 1
        self.db.commit()
        self.assertEqual(reports._collect_pending(self.db, self.settings), [])
        self.lesson.is_paused = 0
        self.db.commit()
        self.assertEqual(len(reports._collect_pending(self.db, self.settings)), 1)

    async def test_manual_request_keeps_date_after_week_boundary(self):
        self.today, self.now = date(2026, 9, 9), self.now + timedelta(days=7)
        self.lesson.lesson_code, self.lesson.lesson_count = "М2У4", "8"
        self.lesson.logika_schedule_id = 108
        self.db.commit()
        await reports.send_report(reports.SendReportRequest(lesson_id=self.lesson.id, lesson_date="2026-09-01"), self.db)
        self.client.get_attendance.assert_called_once_with(101)
        self.assertEqual(self.db.query(ParentReportRun).one().lesson_date, "2026-09-01")
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count), ("М2У4", "8"))

    async def test_manual_review_prefers_saved_schedule_id_when_lesson_time_changes(self):
        run = await self.make_manual_review()
        self.client.get_group_schedule.return_value = [platform_lesson(hour=16, studentsAmount=2),
                                                       platform_lesson(code="М2У3", schedule_id=102, studentsAmount=2)]
        self.client.get_attendance.reset_mock()
        payload = reports.SendReportRequest(lesson_id=self.lesson.id, review_run_id=run.id, lesson_date="2026-09-01")
        preview = await reports.preview_manual_report(payload, self.db)
        self.assertEqual(preview["lesson_code"], "М2У5")
        await reports.send_report(payload, self.db)
        self.assertEqual([call.args[0] for call in self.client.get_attendance.call_args_list], [101, 101])

    async def test_manual_review_uses_group_link_repaired_by_sync(self):
        self.lesson.logika_group_id = None
        self.db.commit()
        await reports.process_auto_reports()
        run = self.db.query(ParentReportRun).one()
        self.assertEqual(run.status, "manual_required")
        self.lesson.logika_group_id = 77
        self.db.commit()
        await reports.send_report(reports.SendReportRequest(lesson_id=self.lesson.id,
                                  lesson_date="2026-09-01", review_run_id=run.id), self.db)
        self.send.assert_awaited_once()

    async def test_double_click_on_manual_review_sends_once(self):
        run = await self.make_manual_review()
        payload = reports.SendReportRequest(lesson_id=self.lesson.id, lesson_date="2026-09-01", review_run_id=run.id)
        results = await asyncio.gather(reports.send_report(payload, self.db), reports.send_report(payload, self.db),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(result, HTTPException) for result in results), 1)
        self.send.assert_awaited_once()
        self.assertEqual(run.status, "success")

    async def check_unknown_review(self, states):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=len(states))]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, states)
        await reports.process_auto_reports()
        run = self.db.query(ParentReportRun).one()
        self.assertEqual(run.status, "manual_required")
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT",) * len(states))
        await reports.process_auto_reports()
        self.send.assert_not_awaited()
        await reports.send_report(reports.SendReportRequest(lesson_id=self.lesson.id, review_run_id=run.id), self.db)
        self.send.assert_awaited_once()

    async def test_unknown_individual_attendance_requires_manual_decision(self):
        await self.check_unknown_review(("UNKNOWN",))

    async def test_unknown_pair_attendance_requires_manual_decision(self):
        await self.check_unknown_review((None, "ABSENT"))

    async def test_pair_without_any_present_student_never_sends(self):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        for states in [("ABSENT", "ABSENT"), ("MISSED", "ABSENT"), ("NO_LESSON", "NO_LESSON")]:
            with self.subTest(states=states):
                self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, states)
                with self.assertRaises(HTTPException) as error:
                    await self.send_report()
                self.assertIn("обидва учні", error.exception.detail)
                self.db.rollback()
                self.assertEqual(self.lesson.lesson_code, "М2У4")
                self.assertEqual(self.lesson.last_report_date, "25-08-2026")
                self.assertEqual(self.lesson.absents, "Введено вручну")
                self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_two_absences_on_different_dates_then_presence(self):
        self.client.get_group_schedule.return_value = [
            platform_lesson(1, "М2У4", 101, contentType="INDIVIDUAL", studentsAmount=1),
            platform_lesson(8, "М2У4", 108, contentType="INDIVIDUAL", studentsAmount=1),
            platform_lesson(15, "М2У5", 115, contentType="INDIVIDUAL", studentsAmount=1),
        ]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(
            schedule_id, ("PRESENT" if schedule_id == 115 else "ABSENT",))
        with patch.object(reports, "_after_report_delivery", AsyncMock()) as followup:
            for lesson_day in (1, 8):
                self.today = date(2026, 9, lesson_day)
                self.now = datetime(2026, 9, lesson_day, 20, tzinfo=reports.KYIV_TZ)
                await reports.process_auto_reports()
                await reports.process_auto_reports()
                self.ai.post.assert_not_awaited()
                self.send.assert_not_awaited()
                followup.assert_not_awaited()
                self.assertEqual(self.db.query(ParentReportRun).count(), 0)
                self.assertEqual(self.lesson.last_report_date, "25-08-2026")
            self.assertTrue(any("01.09.2026" in str(call) for call in self.log.call_args_list))
            self.assertTrue(any("08.09.2026" in str(call) for call in self.log.call_args_list))
            self.today = date(2026, 9, 15)
            self.now = datetime(2026, 9, 15, 20, tzinfo=reports.KYIV_TZ)
            await reports.process_auto_reports()
            await reports.process_auto_reports()
            self.send.assert_awaited_once()
            followup.assert_awaited_once()
            self.assertEqual(self.db.query(ParentReportRun).one().lesson_date, "2026-09-15")
            self.assertEqual([call.args[0] for call in self.client.get_attendance.call_args_list],
                             [101, 101, 108, 108, 115])

    async def test_small_group_presence_is_mandatory_for_manual_and_supplied_text(self):
        for count in (1, 2):
            self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=count)]
            self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT",) * count)
            for message in (None, "Готовий текст звіту"):
                with self.subTest(count=count, supplied=bool(message)):
                    with self.assertRaises(HTTPException) as error:
                        await reports._send_lesson_report(self.db, self.lesson, self.settings, message, "", False, False)
                    self.assertIn("не відправлено", error.exception.detail)
                    self.assertIn("01.09.2026", error.exception.detail)
                    self.db.rollback()
                    self.assertEqual(self.lesson.absents, "Введено вручну")
                    self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()
        self.assertTrue(any("Звіряння уроку з Logika" in str(call) for call in self.log.call_args_list))

    async def test_absent_pair_is_inferred_without_count_or_individual_name(self):
        self.client.get_group_schedule.return_value = [platform_lesson()]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT", "MISSED"))
        with self.assertRaises(HTTPException) as error:
            await reports._send_lesson_report(self.db, self.lesson, self.settings, "Готовий текст", "", True, False)
        self.assertIn("обидва учні", error.exception.detail)
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_pair_with_individual_marker_can_send_when_present(self):
        self.client.get_group_schedule.return_value = [platform_lesson(contentType="INDIVIDUAL", studentsAmount=2)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "PRESENT"))
        await self.send_report()
        self.send.assert_awaited_once()

    async def test_pair_scheduler_rechecks_and_does_not_schedule_absent_followup(self):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT", "ABSENT"))
        with patch.object(reports, "_after_report_delivery", AsyncMock()) as followup:
            await reports.process_auto_reports()
            await reports.process_auto_reports()
            self.ai.post.assert_not_awaited()
            self.send.assert_not_awaited()
            followup.assert_not_awaited()
            self.assertEqual(self.db.query(ParentReportRun).count(), 0)
            self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "PRESENT"))
            await reports.process_auto_reports()
            await reports.process_auto_reports()
            self.send.assert_awaited_once()
            followup.assert_awaited_once()
            self.assertEqual(self.db.query(ParentReportRun).count(), 1)

    async def test_small_group_resend_cannot_bypass_presence_with_manual_absents(self):
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=2)]
        await self.send_report()
        original = self.db.query(ParentReportRun).one()
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT", "ABSENT"))
        with self.assertRaises(HTTPException) as error:
            await reports.resend_report(original.id, reports.ResendReportRequest(
                request_id=uuid4(), absents="", use_logika_absents=False), self.db)
        self.assertIn("обидва учні", error.exception.detail)
        self.assertEqual(self.db.query(ParentReportRun).count(), 1)
        self.assertEqual(self.ai.post.await_count, 1)
        self.assertEqual(self.send.await_count, 1)

    async def test_larger_group_with_absent_student_still_sends(self):
        self.config.auto_fetch_absents = 1
        self.client.get_group_schedule.return_value = [platform_lesson(studentsAmount=3)]
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("ABSENT", "PRESENT", "PRESENT"))
        await self.send_report()
        self.send.assert_awaited_once()
        self.assertEqual(self.db.query(ParentReportRun).one().absents, "Учень 1")

    async def test_confirmed_no_absences_clears_previous_lesson_absentees(self):
        self.config.auto_fetch_absents = 1
        await self.sync()
        self.assertEqual(self.lesson.absents, "")

    async def test_outage_waits_without_ai_or_send_then_retries_once(self):
        self.client.get_group_schedule.side_effect = RuntimeError("Logika недоступна")
        await reports.process_auto_reports()
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()
        self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.assertTrue(any("Автозвіт" in str(call) and "Logika недоступна" in str(call)
                            for call in self.log.call_args_list))
        self.client.get_group_schedule.side_effect = None
        await reports.process_auto_reports()
        await reports.process_auto_reports()
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.ai.post.await_count, 1)

    async def test_unverifiable_lesson_never_uses_old_material(self):
        cases = [
            [], [platform_lesson(8)], [platform_lesson(code="Без коду")],
            [platform_lesson(code="М9У9")], [platform_lesson(teacher={"key": 33})],
            [platform_lesson(group={"key": 88})], [platform_lesson(teacher={})],
            [platform_lesson(group={})], [platform_lesson(lessonStatus="CANCEL")],
            [platform_lesson(deleted=True)],
            [platform_lesson(hour=12), platform_lesson(hour=16, schedule_id=102)],
        ]
        for items in cases:
            with self.subTest(items=items):
                self.client.get_group_schedule.return_value = items
                with self.assertRaises(HTTPException):
                    await self.send_report()
                self.db.rollback()
                self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count), ("М2У4", "8"))
        self.ai.post.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_time_disambiguates_two_lessons_on_same_day(self):
        self.client.get_group_schedule.return_value = [
            platform_lesson(hour=10, code="М2У3", schedule_id=100), platform_lesson(),
        ]
        await self.sync()
        self.assertEqual((self.lesson.logika_schedule_id, self.lesson.lesson_code), (101, "М2У5"))

    async def test_platform_duration_must_have_ended(self):
        self.today = date(2026, 9, 1)
        self.now = datetime(2026, 9, 1, 15, 45, tzinfo=reports.KYIV_TZ)  # Local delay passed; Logika lesson still running.
        self.client.get_group_schedule.return_value = [platform_lesson(duration=7200)]
        with self.assertRaises(HTTPException) as error:
            await self.send_report()
        self.assertIn("ще не завершився", error.exception.detail)
        self.ai.post.assert_not_awaited()

    async def test_timezone_is_converted_to_kyiv_before_date_match(self):
        self.lesson.start_time = "00:30"
        self.client.get_group_schedule.return_value = [platform_lesson(start="2026-08-31T21:30:00Z")]
        await self.sync()
        self.assertEqual(self.lesson.lesson_code, "М2У5")

    async def test_ai_uses_code_even_with_conflicting_number(self):
        self.lesson.lesson_code, self.lesson.lesson_count = "М2У3", "8"
        await reports._generate_ai_report(self.settings, self.lesson, "")
        self.assertEqual(self.lesson.lesson_count, "7")
        self.assertIn("Матеріал М2У3", self.ai.post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])

    async def test_selecting_course_keeps_code_and_resolves_its_number(self):
        self.lesson.course = ""
        self.lesson.lesson_code, self.lesson.lesson_count = "М2У3", "8"
        self.db.commit()
        await reports.update_schedule_row(self.lesson.id, reports.ScheduleUpdate(course=COURSE), self.db)
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count), ("М2У3", "7"))

    async def test_changing_code_manually_updates_number(self):
        await reports.update_schedule_row(self.lesson.id, reports.ScheduleUpdate(lesson_code="М2У3"), self.db)
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count), ("М2У3", "7"))

    async def test_full_sync_does_not_use_chronological_position_as_number(self):
        self.client.get_schedule.return_value = [platform_lesson()]
        self.client.get_group_schedule.return_value = [platform_lesson(code="М2У3")]
        await logika.sync_schedule(self.db)
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count), ("М2У3", "7"))
        self.assertEqual(self.lesson.telegram_group_id, self.group.id)
        self.assertEqual(self.lesson.last_report_date, "25-08-2026")
        self.lesson.course = ""
        self.db.commit()
        await logika.sync_schedule(self.db)
        self.assertEqual(self.lesson.lesson_count, "7")

    async def test_full_sync_preserves_absents_and_never_relinks_by_same_name(self):
        self.client.get_schedule.return_value = [platform_lesson(group={"key": 88, "value": self.lesson.group_name})]
        self.client.get_group_schedule.return_value = [platform_lesson(group={"key": 88, "value": self.lesson.group_name})]
        await logika.sync_schedule(self.db)
        self.assertEqual(self.lesson.logika_group_id, 77)
        self.assertEqual(self.lesson.absents, "Введено вручну")
        self.assertEqual(self.lesson.course, COURSE)
        self.assertEqual(self.db.query(ParentReportLesson).count(), 2)
        self.client.get_attendance.assert_not_called()
        self.client.get_absent_students.assert_not_called()

    async def test_full_sync_preserves_pause_and_postponement_for_matched_group(self):
        self.lesson.is_paused = 1
        self.lesson.postponed_start_at = "2026-09-08T14:00:00+03:00"
        self.db.commit()
        self.client.get_schedule.return_value = [platform_lesson()]
        self.client.get_group_schedule.return_value = [platform_lesson()]
        await logika.sync_schedule(self.db)
        self.db.refresh(self.lesson)
        self.assertEqual(self.db.query(ParentReportLesson).count(), 1)
        self.assertEqual(self.lesson.is_paused, 1)
        self.assertEqual(self.lesson.postponed_start_at, "2026-09-08T14:00:00+03:00")
        self.assertEqual(self.lesson.course, COURSE)
        self.assertEqual(self.lesson.absents, "Введено вручну")

    async def test_full_sync_ignores_cancelled_wrong_teacher_and_converts_timezone(self):
        self.client.get_schedule.return_value = [platform_lesson()]
        self.client.get_group_schedule.return_value = [
            platform_lesson(day=2, lessonStatus="CANCEL", code="М2У3"),
            platform_lesson(day=2, teacher={"key": 33}, code="М2У3"),
            platform_lesson(day=2, group={"key": 88}, code="М2У3"),
            platform_lesson(start="2026-09-01T21:30:00Z", code="М2У4"),
        ]
        self.lesson.day = self.lesson.start_time = ""
        self.db.commit()
        await logika.sync_schedule(self.db)
        self.assertEqual((self.lesson.day, self.lesson.start_time, self.lesson.lesson_code), ("Ср", "00:30", "М2У4"))

    async def test_full_sync_cannot_change_topic_while_ai_is_preparing_report(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original_ai = self.ai.post.return_value

        async def slow_ai(*args, **kwargs):
            entered.set()
            await release.wait()
            return original_ai

        self.ai.post.side_effect = slow_ai
        self.client.get_schedule.return_value = [platform_lesson()]
        other = self.sessions()
        # The synchronizer may already have loaded the row before waiting for the lock.
        other.get(ParentReportLesson, self.lesson.id)
        report = asyncio.create_task(self.send_report())
        await asyncio.wait_for(entered.wait(), 2)
        syncing = asyncio.create_task(logika.sync_schedule(other))
        try:
            await asyncio.sleep(0.02)
            self.client.get_schedule.assert_not_called()
            self.assertFalse(syncing.done())
            release.set()
            await report
            await syncing
            self.db.expire_all()
            run = self.db.query(ParentReportRun).one()
            self.assertEqual(run.lesson_date, "2026-09-01")
            prompt = self.ai.post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
            self.assertIn("М2У5|9|Матеріал М2У5", prompt)
            self.assertEqual(self.lesson.last_report_date, "01-09-2026")
            self.assertEqual(self.lesson.course, COURSE)
            self.send.assert_awaited_once()
        finally:
            release.set()
            await asyncio.gather(report, syncing, return_exceptions=True)
            other.close()


    async def test_sync_filters_status_type_and_teacher_without_deleting_saved_rows(self):
        items = []
        for index, (status, kind, teacher) in enumerate([
            ("ACTIVE", "GROUP", 22), ("ACTIVE", "INDIVIDUAL", 22),
            ("RECRUITING", "GROUP", 22), ("RECRUITING", "INDIVIDUAL", 22),
            ("ACTIVE", "MASTER_CLASS", 22), ("RECRUITING", "MASTER_CLASS", 22),
            ("FINISH", "GROUP", 22), ("ACTIVE", "INTENSIVE", 22),
            ("ACTIVE", None, 22), ("RECRUITING", "GROUP", 23),
        ], start=200):
            items.append(platform_lesson(schedule_id=index, group={"key": index, "value": f"Group {index}"},
                                         groupStatus=status, contentType=kind, teacher={"key": teacher}))
        self.client.get_schedule.return_value = items
        self.client.get_group_schedule.side_effect = lambda key: [next(x for x in items if x["group"]["key"] == key)]
        result = await logika.sync_schedule(self.db)
        self.assertEqual((result["added"], result["total"]), (4, 4))
        self.assertEqual({x.logika_group_id for x in self.db.query(ParentReportLesson)}, {77, 200, 201, 202, 203})
        self.assertEqual(self.lesson.course, COURSE)
        self.client.get_schedule.assert_called_once_with(page=0, size=100, teacher_id=22,
            status="ACTIVE,RECRUITING", active=None, is_start_day_now=False,
            content_types="GROUP,INDIVIDUAL", all_pages=True)

    async def test_slow_network_does_not_block_event_loop_and_cancellation_keeps_database(self):
        entered, release = threading.Event(), threading.Event()
        def slow_schedule(**kwargs):
            entered.set()
            release.wait(2)
            return [platform_lesson()]
        self.client.get_schedule.side_effect = slow_schedule
        work = asyncio.create_task(logika.sync_schedule(self.db))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            self.assertFalse(work.done())
            work.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await work
            self.client.cancel.assert_called_once()
            self.assertEqual(self.db.query(ParentReportLesson).count(), 1)
            self.client.get_group_schedule.assert_not_called()
        finally:
            release.set()

    async def test_authentication_and_group_requests_run_off_event_loop(self):
        main_thread = threading.get_ident()
        def network(result):
            def call(*args, **kwargs):
                self.assertNotEqual(threading.get_ident(), main_thread)
                return result
            return call
        self.client.access_token = None
        self.client.authenticate.side_effect = network({"access_token": "new"})
        self.client.get_schedule.side_effect = network([platform_lesson()])
        self.client.get_group_schedule.side_effect = network([platform_lesson()])
        self.client.get_absent_students.side_effect = network([])
        await logika.sync_schedule(self.db)
        self.client.authenticate.assert_called_once()


    async def test_resend_checks_original_date_and_clears_stale_absents_without_changing_current_lesson(self):
        self.config.auto_fetch_absents = 1
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id, ("PRESENT", "ABSENT", "PRESENT"))
        await self.send_report()
        original = self.db.query(ParentReportRun).one()
        self.assertEqual(original.absents, "Учень 2")
        self.lesson.lesson_code = "М2У4"
        self.lesson.lesson_count = "8"
        self.lesson.absents = "Наступний урок — вручну"
        self.lesson.last_report_date = "08-09-2026"
        self.lesson.logika_schedule_id = 108
        self.config.auto_fetch_absents = 0
        self.db.commit()
        self.today = date(2026, 9, 16)
        self.now += timedelta(days=14)
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(schedule_id)
        preview = await reports.preview_report_resend(original.id, self.db)
        self.assertEqual((preview["lesson_date"], preview["lesson_code"], preview["absents"]),
                         ("2026-09-01", "М2У5", ""))
        await reports.resend_report(original.id, reports.ResendReportRequest(request_id=uuid4()), self.db)
        prompt = self.ai.post.await_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("М2У5|9|Матеріал М2У5|", prompt)
        self.assertNotIn("Учень 2", prompt)
        self.client.get_attendance.assert_called_with(101)
        self.db.refresh(self.lesson)
        self.assertEqual((self.lesson.lesson_code, self.lesson.lesson_count, self.lesson.absents,
                          self.lesson.logika_schedule_id, self.lesson.last_report_date),
                         ("М2У4", "8", "Наступний урок — вручну", 108, "08-09-2026"))
        self.assertEqual(self.db.get(ParentReportRun, original.id).absents, "Учень 2")
        self.assertEqual(self.send.await_count, 2)

    async def test_resend_legacy_logika_report_finds_lesson_by_original_date(self):
        await self.send_report()
        original = self.db.query(ParentReportRun).one()
        original.lesson_snapshot = None
        self.lesson.lesson_code = "М2У4"
        self.lesson.logika_schedule_id = 108
        self.db.commit()
        self.client.get_attendance.reset_mock()
        preview = await reports.preview_report_resend(original.id, self.db)
        self.assertEqual(preview["lesson_code"], "М2У5")
        self.client.get_attendance.assert_called_once_with(101)
        self.db.refresh(self.lesson)
        self.assertEqual(self.lesson.lesson_code, "М2У4")

    async def test_resend_manual_absents_override_and_known_schedule_id(self):
        await self.send_report()
        original = self.db.query(ParentReportRun).one()
        self.client.get_group_schedule.return_value = [platform_lesson(hour=16),
                                                       platform_lesson(code="М2У3", schedule_id=102)]
        self.client.get_attendance.reset_mock()
        await reports.resend_report(original.id, reports.ResendReportRequest(
            request_id=uuid4(), absents="Уточнено викладачем", use_logika_absents=False,
        ), self.db)
        prompt = self.ai.post.await_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("М2У5|9|Матеріал М2У5|Уточнено викладачем", prompt)
        self.client.get_attendance.assert_called_once_with(101)

    async def test_resend_rejects_wrong_attendance_schedule_before_generation(self):
        await self.send_report()
        original = self.db.query(ParentReportRun).one()
        self.client.get_attendance.side_effect = lambda schedule_id: attendance(108)
        with self.assertRaises(HTTPException):
            await reports.resend_report(original.id, reports.ResendReportRequest(request_id=uuid4()), self.db)
        self.assertEqual(self.ai.post.await_count, 1)
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.db.query(ParentReportRun).count(), 1)


class LogikaPaginationTests(unittest.TestCase):
    def test_attendance_validates_schedule_and_deduplicates_students(self):
        records = attendance(101, ("PRESENT",)) * 2
        self.assertEqual(len(parse_attendance(records, 101)), 1)
        self.assertEqual(parse_attendance(attendance(101, ("NO_LESSON",)), 101)[0]["state"], "NO_LESSON")
        with self.assertRaises(ValueError):
            parse_attendance(records, 108)

    def test_attendance_api_checks_schedule_id(self):
        client = LogikaClient(access_token="fake")
        response = SimpleNamespace(status_code=200, json=lambda: attendance(108, ("PRESENT",)))
        with patch.object(client, "_authorized_request", return_value=response) as request:
            with self.assertRaises(ValueError):
                client.get_attendance(101)
        self.assertEqual(request.call_args.kwargs["params"], {"scheduleId": 101})

    def test_group_schedule_reads_small_pages_when_server_says_more_exist(self):
        client = LogikaClient(access_token="fake")
        pages = [SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": 1}], "last": False}),
                 SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": 2}], "last": True})]
        with patch.object(client, "_authorized_request", side_effect=pages):
            self.assertEqual([item["id"] for item in client.get_group_schedule(77)], [1, 2])

    def test_discovery_reads_all_pages_even_when_server_caps_page_size(self):
        client = LogikaClient(access_token="fake")
        pages = [SimpleNamespace(status_code=200, json=lambda: {
            "content": [{"id": 1}], "last": False, "totalPages": 2}),
            SimpleNamespace(status_code=200, json=lambda: {
                "content": [{"id": 2}], "last": True, "totalPages": 2})]
        with patch.object(client, "_authorized_request", side_effect=pages) as request:
            result = client.get_schedule(status="ACTIVE,RECRUITING", content_types="GROUP,INDIVIDUAL",
                                         active=None, is_start_day_now=False, all_pages=True)
        self.assertEqual([x["id"] for x in result], [1, 2])
        self.assertEqual([c.kwargs["params"]["page"] for c in request.call_args_list], [0, 1])
        params = request.call_args_list[0].kwargs["params"]
        self.assertEqual(params["status"], "ACTIVE,RECRUITING")
        self.assertEqual(params["type"], "GROUP,INDIVIDUAL")
        self.assertNotIn("active", params)

    def test_discovery_repeated_page_fails(self):
        client = LogikaClient(access_token="fake")
        response = SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": 1}], "last": False})
        with patch.object(client, "_authorized_request", return_value=response) as request:
            with self.assertRaisesRegex(Exception, "повторює сторінку"):
                client.get_schedule(all_pages=True)
        self.assertEqual(request.call_count, 2)

    def test_discovery_later_page_failure_does_not_return_partial_results(self):
        client = LogikaClient(access_token="fake")
        responses = [SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": 1}], "last": False}),
                     SimpleNamespace(status_code=503, text="Unavailable")]
        with patch.object(client, "_authorized_request", side_effect=responses):
            with self.assertRaisesRegex(Exception, "HTTP 503"):
                client.get_schedule(all_pages=True)

    def test_reads_later_pages_for_finished_lesson(self):
        client = LogikaClient(access_token="fake")
        pages = [
            SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": n} for n in range(100)], "last": False}),
            SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": 101}], "last": True}),
        ]
        with patch.object(client, "_authorized_request", side_effect=pages) as request:
            self.assertEqual(len(client.get_group_schedule(77)), 101)
        self.assertEqual([c.kwargs["params"]["page"] for c in request.call_args_list], [0, 1])

    def test_http_failure_is_not_an_empty_schedule(self):
        client = LogikaClient(access_token="fake")
        with patch.object(client, "_authorized_request", return_value=SimpleNamespace(status_code=503)):
            with self.assertRaisesRegex(Exception, "HTTP 503"):
                client.get_group_schedule(77)

    def test_repeated_page_stops_instead_of_looping(self):
        client = LogikaClient(access_token="fake")
        response = SimpleNamespace(status_code=200, json=lambda: {"content": [{"id": n} for n in range(100)]})
        with patch.object(client, "_authorized_request", return_value=response) as request:
            with self.assertRaisesRegex(Exception, "повторює сторінку"):
                client.get_group_schedule(77)
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
