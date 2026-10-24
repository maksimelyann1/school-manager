from datetime import datetime
import json
from unittest.mock import patch

from test_task_planner import PlannerFixture
from models import ParentReportCourse, ParentReportCourseLesson, ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import assistant
from routers.parents_report import KYIV_TZ


class AssistantReportTests(PlannerFixture):
    def setUp(self):
        super().setUp()
        self.client.app.include_router(assistant.router, prefix="/api")
        self.clock = patch.object(assistant, "datetime", wraps=datetime).start()
        self.addCleanup(patch.stopall)
        self.clock.now.return_value = datetime(2026, 10, 23, 18, tzinfo=KYIV_TZ)
        self.db.add(ParentReportSettings(default_duration_minutes=60, report_delay_minutes=10))
        self.db.commit()

    def lesson(self, **values):
        row = ParentReportLesson(**{"group_name": "Максим", "day": "ПТ", "start_time": "11:00", **values})
        self.db.add(row)
        self.db.commit()
        return row

    def add_run(self, lesson, status="success", **values):
        row = ParentReportRun(**{"lesson_id": lesson.id, "lesson_group_name": lesson.group_name,
            "lesson_date": "2026-10-23", "status": status, "created_at": "2026-10-23T12:15:00+03:00",
            "telegram_message_id": 123 if status == "success" else None, **values})
        self.db.add(row)
        self.db.commit()
        return row

    def audit(self, **params):
        response = self.client.get("/api/assistant/reports", params={"start": "2026-10-23", "end": "2026-10-23", **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_empty_is_not_all_sent_and_reads_create_no_settings(self):
        self.db.query(ParentReportSettings).delete()
        self.db.commit()
        result = self.audit()
        self.assertIsNone(result["all_sent"])
        self.assertEqual(self.db.query(ParentReportSettings).count(), 0)

    def test_success_then_failed_resend_still_counts_original_delivery(self):
        lesson = self.lesson()
        first = self.add_run(lesson)
        self.add_run(lesson, "error", error="Forbidden", resend_of_run_id=first.id)
        self.assertTrue(self.audit()["all_sent"])
        self.assertEqual(self.audit()["counts"], {"sent": 1})

    def test_test_success_cannot_hide_missing_report(self):
        self.add_run(self.lesson(), is_test=1)
        result = self.audit()
        self.assertFalse(result["all_sent"])
        self.assertEqual(result["counts"], {"missing": 1})

    def test_uncertain_and_ambiguous_errors_are_unconfirmed(self):
        self.add_run(self.lesson(), "uncertain")
        self.add_run(self.lesson(group_name="Інша група"), "error", error="Request timed out")
        result = self.audit()
        self.assertFalse(result["all_sent"])
        self.assertEqual(result["counts"], {"unconfirmed": 2})

    def test_marker_without_delivery_evidence_is_unconfirmed(self):
        self.lesson(last_report_date="23.10.2026")
        self.assertEqual(self.audit()["counts"], {"unconfirmed": 1})

    def test_pause_future_postpone_and_report_delay(self):
        self.lesson(group_name="Пауза", is_paused=1)
        self.lesson(group_name="Перенесено", postponed_start_at="2026-10-24T11:00:00+03:00")
        self.lesson(group_name="Ще триває", start_time="17:00")
        result = self.audit()
        self.assertIsNone(result["all_sent"])
        self.assertEqual(len(result["not_due"]), 1)
        self.assertEqual(len(result["excluded"]), 1)

    def test_saved_snapshot_keeps_historical_occurrence(self):
        row = self.lesson(start_time="23:00")
        self.add_run(row, "manual_required", lesson_snapshot=json.dumps({
            "start_at": "2026-10-23T11:00:00+03:00", "duration_minutes": 60}))
        result = self.audit()
        self.assertEqual(result["counts"], {"manual_required": 1})
        self.assertEqual(result["items"][0]["schedule_source"], "saved_occurrence")

    def test_deleted_row_stays_visible_in_delivery_log(self):
        row = self.lesson()
        self.add_run(row, "error", error="Forbidden")
        self.db.delete(row)
        self.db.commit()
        self.assertEqual(self.audit()["counts"], {"error": 1})

    def test_invalid_schedule_prevents_all_sent(self):
        self.add_run(self.lesson())
        self.lesson(group_name="Пошкоджений рядок", day="???")
        result = self.audit()
        self.assertIsNone(result["all_sent"])
        self.assertEqual(len(result["invalid_schedule"]), 1)

    def test_legacy_name_cannot_confirm_two_same_name_lessons(self):
        row = self.lesson()
        self.lesson(start_time="13:00")
        self.add_run(row, lesson_id=None)
        result = self.audit()
        self.assertFalse(result["all_sent"])
        self.assertEqual(result["counts"]["missing"], 2)

    def test_filter_and_period_boundaries(self):
        self.add_run(self.lesson())
        self.lesson(group_name="Інша група")
        self.assertTrue(self.audit(group="макс")["all_sent"])
        response = self.client.get("/api/assistant/reports?start=2026-09-01&end=2026-10-23")
        self.assertEqual(response.status_code, 422)

    def test_orphan_legacy_reports_for_different_groups_never_merge(self):
        first = self.lesson()
        second = self.lesson(group_name="Інша група")
        self.add_run(first, lesson_id=None)
        self.add_run(second, "error", lesson_id=None, error="Forbidden")
        self.db.query(ParentReportLesson).delete()
        self.db.commit()
        result = self.audit()
        self.assertFalse(result["all_sent"])
        self.assertEqual(result["counts"], {"sent": 1, "error": 1})

    def test_identity_is_available_without_database_setup(self):
        result = self.client.get("/api/assistant/status").json()
        self.assertEqual(result["service"], "school_manager")
        self.assertIn("report_audit", result["capabilities"])

    def test_course_detail_is_read_only_and_keeps_report_settings(self):
        course = ParentReportCourse(name="Курс", source_sheet="Курс", updated_at="unchanged")
        self.db.add(course)
        self.db.flush()
        topic = ParentReportCourseLesson(course_id=course.id, course_name=course.name,
            source_sheet="Курс", lesson_count=1, lesson_title="Тема", lesson_report_text="Матеріал")
        self.db.add(topic)
        self.db.commit()
        response = self.client.get(f"/api/assistant/courses/{course.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lessons"][0]["lesson_report_text"], "Матеріал")
        self.db.refresh(course)
        self.assertEqual(course.updated_at, "unchanged")
        self.assertEqual(self.db.query(ParentReportRun).count(), 0)
        self.assertFalse(self.db.query(ParentReportSettings).first().auto_reports_enabled)
        self.assertEqual(self.client.get("/api/assistant/courses/9999").status_code, 404)
