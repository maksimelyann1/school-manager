import asyncio
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from logika_client import LogikaClient
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
        "teacher": {"key": 22}, "groupStatus": "ACTIVE", "lessonStatus": "FINISH",
        "start": f"2026-09-{day:02d}T{hour:02d}:00:00+03:00", "duration": 5400,
        "lesson": {"value": f"{code} Тема з платформи"},
    }
    item.update(changes)
    return item


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
        self.log = self.stack.enter_context(patch.object(reports, "log_event"))
        self.stack.enter_context(patch.object(logika, "log_event"))
        self.source = self.stack.enter_context(patch.object(
            reports, "_load_source_course_lessons", AsyncMock(return_value=MATERIALS)))
        self.client = Mock(access_token="fake", refresh_token=None, xsrf_token=None)
        self.client.get_group_schedule.return_value = [
            platform_lesson(8, "М2У4", 108), platform_lesson(1, "М2У5", 101),
        ]
        self.client.get_absent_students.return_value = []
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
        self.client.get_absent_students.assert_not_called()

    async def test_attendance_uses_finished_schedule_id(self):
        self.config.auto_fetch_absents = 1
        self.client.get_absent_students.return_value = ["Учень"]
        await self.sync()
        self.client.get_absent_students.assert_called_once_with(101)
        self.assertEqual(self.lesson.absents, "Учень")

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
            [platform_lesson(group={"key": 88})], [platform_lesson(lessonStatus="CANCEL")],
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
        self.now = datetime(2026, 9, 1, 15, 35, tzinfo=reports.KYIV_TZ)
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


class LogikaPaginationTests(unittest.TestCase):
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
