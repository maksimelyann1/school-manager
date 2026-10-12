"""Local widget data; no external synchronization or changes to reports."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import ParentReportLesson, ParentReportSettings
from routers.parents_report import KYIV_TZ, _lesson_schedule_context
from services.planner.routes import PlannerRoute

router = APIRouter(prefix='/widgets', tags=['Віджети'], route_class=PlannerRoute)


@router.get('/lessons')
def upcoming_lessons(db: Session = Depends(get_db)):
    now = datetime.now(KYIV_TZ)
    settings = db.query(ParentReportSettings).first() or ParentReportSettings(default_duration_minutes=90)
    result = []
    for lesson in db.query(ParentReportLesson).filter(ParentReportLesson.is_paused == 0).all():
        schedule = _lesson_schedule_context(lesson, settings)
        if not schedule:
            continue
        start, end = schedule['start_dt'], schedule['end_dt']
        if schedule['is_postponed']:
            if end <= now:
                continue
        elif end <= now:
            start += timedelta(days=7); end += timedelta(days=7)
        result.append({'id': lesson.id, 'title': lesson.group_name, 'start': start.isoformat(), 'end': end.isoformat(),
                       'lesson_code': lesson.lesson_code, 'lesson_title': lesson.lesson_title, 'postponed': schedule['is_postponed']})
    return {'items': sorted(result, key=lambda item: item['start'])[:30]}
