from datetime import datetime, timedelta
from unittest.mock import patch
from test_task_planner import PlannerFixture
from models import ParentReportLesson
from routers import widgets
from routers.parents_report import KYIV_TZ
from services.planner import google_sync


class WidgetDataTests(PlannerFixture):
    def test_widgets_do_not_change_google_active_interval(self):
        self.create(title='Справа')
        with patch.object(google_sync, 'touch_activity') as activity:
            response = self.client.get('/api/tasks?bucket=undated&track_activity=false')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()['items']), 1)
            activity.assert_not_called()
            self.client.get('/api/tasks?bucket=undated')
            activity.assert_called_once()

    def test_pauses_postponements_and_next_week_are_preserved(self):
        now = datetime(2026, 10, 11, 18, tzinfo=KYIV_TZ)
        self.db.add_all([
            ParentReportLesson(group_name='Минув сьогодні', day='НД', start_time='10:00'),
            ParentReportLesson(group_name='Пауза', day='НД', start_time='19:00', is_paused=1),
            ParentReportLesson(group_name='Перенесено', day='НД', start_time='19:00', postponed_start_at=(now + timedelta(days=10)).isoformat()),
        ])
        self.db.commit()
        with patch.object(widgets, 'datetime') as clock, patch('routers.parents_report._today_kyiv', return_value=now.date()):
            clock.now.return_value = now
            items = widgets.upcoming_lessons(self.db)['items']
        self.assertEqual([item['title'] for item in items], ['Минув сьогодні', 'Перенесено'])
        self.assertEqual(items[0]['start'], '2026-10-18T10:00:00+03:00')
        self.assertEqual(items[1]['start'], (now + timedelta(days=10)).isoformat())
        self.assertEqual(self.db.query(ParentReportLesson).count(), 3)
