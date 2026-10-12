"""Manual reports UI with isolated SQLite and fake Logika, AI and Telegram."""
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime
from unittest.mock import patch

import report_resend_preview as preview
from models import ParentReportLesson, ParentReportRun, ParentReportSettings
from routers import dashboard, parents_report as reports

now = datetime(2026, 9, 2, 20, tzinfo=reports.KYIV_TZ)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return now.astimezone(tz) if tz else now.replace(tzinfo=None)


@asynccontextmanager
async def lifespan(app):
    global now
    async with preview.lifespan(app):
        with ExitStack() as stack:
            stack.enter_context(patch.object(reports, "SessionLocal", preview.sessions))
            stack.enter_context(patch.object(reports, "datetime", Clock))
            stack.enter_context(patch.object(dashboard, "datetime", Clock))
            stack.enter_context(patch.object(reports, "_today_kyiv", lambda: now.date()))
            preview.logika.get_attendance.side_effect = lambda schedule_id: [
                {"scheduleId": schedule_id, "studentId": {"key": n, "value": f"Учень {n}"},
                 "state": "PRESENT" if n == 1 else "ABSENT"} for n in (1, 2)
            ]
            with preview.sessions() as db:
                db.query(ParentReportRun).delete()
                lesson = db.get(ParentReportLesson, 1)
                lesson.day, lesson.last_report_date = "ВТ", "25-08-2026"
                db.query(ParentReportSettings).first().auto_reports_enabled = 1
                db.commit()
            await reports.process_auto_reports()
            now = datetime(2026, 9, 9, 20, tzinfo=reports.KYIV_TZ)
            with preview.sessions() as db:
                lesson = db.get(ParentReportLesson, 1)
                lesson.last_report_date = "08-09-2026"
                db.commit()
            yield


app = preview.app
app.router.lifespan_context = lifespan

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8767)
