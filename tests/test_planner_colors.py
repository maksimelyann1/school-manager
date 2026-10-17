import asyncio
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_task_planner import PlannerFixture
from task_models import PlannerItem, PlannerExternalLink, PlannerSyncJob
from services.planner import google_sync as google
from services.planner.colors import EVENT_COLORS, event_color, google_color_id


class PlannerColorTests(PlannerFixture):
    def remote(self, color_id='3', etag='v1'):
        return {'id': 'colored', 'etag': etag, 'summary': 'Подія', 'colorId': color_id,
                'start': {'date': '2030-01-01'}, 'end': {'date': '2030-01-02'}}

    def import_event(self, color_id='3'):
        calendar = self.connect(managed=False)
        calendar.writable, calendar.sync_format, calendar.color = 1, 3, '#123456'
        google.apply_remote(self.db, calendar, self.remote(color_id))
        self.db.commit()
        return calendar, self.db.query(PlannerItem).one()

    def test_ui_palette_matches_google_ids(self):
        source = (Path(__file__).resolve().parents[1] / 'frontend/src/components/PlannerEventMenu.jsx').read_text(encoding='utf-8')
        self.assertEqual(set(re.findall(r"'(#[a-f0-9]{6})'", source)), set(EVENT_COLORS.values()))
        for key, color in EVENT_COLORS.items():
            self.assertEqual(google_color_id(color.upper()), key)
            self.assertEqual(event_color(key), color)
        self.assertIsNone(google_color_id(None))
        self.assertIsNone(event_color('0'))

    def test_local_color_stays_local_and_google_color_is_queued(self):
        self.connect()
        for enabled in (False, True):
            item = self.create(date='2030-01-01', google_enabled=enabled)
            response = self.client.patch(f'/api/tasks/{item["id"]}/color', json={'revision': 1, 'color': '#dc2127'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['color'], '#dc2127')
            self.assertEqual(response.json()['sync_state'], 'pending' if enabled else 'local')

    def test_google_color_and_default_calendar_color_are_imported(self):
        calendar, item = self.import_event()
        response = self.client.get(f'/api/tasks/{item.id}').json()
        self.assertEqual(response['color'], '#dbadff')
        self.assertEqual(response['calendar_color'], '#123456')
        google.apply_remote(self.db, calendar, self.remote(None, 'v2'))
        self.db.commit()
        self.assertIsNone(self.db.get(PlannerItem, item.id).color)

    def test_color_patch_and_reset_only_modify_google_color(self):
        calendar, item = self.import_event()
        for color, expected in [('#dc2127', '11'), (None, None)]:
            revision = item.revision
            response = self.client.patch(f'/api/tasks/{item.id}/color', json={'revision': revision, 'color': color})
            self.assertEqual(response.status_code, 200, response.text)
            self.db.expire_all()
            snapshot = json.loads(self.db.query(PlannerExternalLink).one().snapshot)
            body = google.changed_event_body(item, snapshot, calendar)
            self.assertEqual(body, {'colorId': expected})

            async def write(method, path, **kwargs):
                self.assertEqual(method, 'PATCH')
                self.assertEqual(kwargs['json'], {'colorId': expected})
                return {**snapshot, **kwargs['json'], 'etag': str(revision)}

            asyncio.run(google.push_job(self.db, SimpleNamespace(request=write), calendar, self.db.query(PlannerSyncJob).one()))
            self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)
            self.assertEqual(item.color, color)

    def test_existing_color_is_backfilled_with_unchanged_etag_without_overwriting_pending_edit(self):
        calendar, item = self.import_event()
        calendar.sync_format, item.color = 2, None
        self.db.commit()
        google.apply_remote(self.db, calendar, self.remote())
        self.db.commit()
        self.assertEqual(item.color, '#dbadff')
        self.client.patch(f'/api/tasks/{item.id}/color', json={'revision': item.revision, 'color': '#dc2127'})
        self.db.expire_all()
        google.apply_remote(self.db, calendar, self.remote())
        self.assertEqual(item.color, '#dc2127')

    def test_color_mismatch_cannot_acknowledge_lost_write(self):
        calendar, item = self.import_event()
        expected, actual = self.remote('11'), self.remote('3')
        self.assertFalse(google.equivalent_event(expected, actual, calendar))
        self.assertTrue(google.equivalent_event(expected, self.remote('11'), calendar))

    def test_readonly_calendar_rejects_color_changes(self):
        calendar, item = self.import_event()
        item.read_only = 1
        self.db.commit()
        response = self.client.patch(f'/api/tasks/{item.id}/color', json={'revision': 1, 'color': '#dc2127'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_creation_push_includes_color(self):
        calendar = self.connect()
        saved = self.create(date='2030-01-01', google_enabled=True)
        self.client.patch(f'/api/tasks/{saved["id"]}/color', json={'revision': 1, 'color': '#51b749'})
        self.db.expire_all()
        async def write(method, path, **kwargs):
            self.assertEqual(kwargs['json']['colorId'], '10')
            return {**kwargs['json'], 'etag': 'created'}
        asyncio.run(google.push_job(self.db, SimpleNamespace(request=write), calendar, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(self.db.get(PlannerItem, saved['id']).color, '#51b749')
