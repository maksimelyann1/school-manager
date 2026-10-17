import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_task_planner import PlannerFixture
from services.planner import google_sync as google
from task_models import PlannerItem, PlannerExternalLink, PlannerSyncJob


class AutoMergeTests(PlannerFixture):
    def setUp(self):
        super().setUp()
        self.logging = patch('logger.log_event')
        self.logging.start()
        self.addCleanup(self.logging.stop)
        self.calendar = self.connect()
        self.calendar.sync_format = 3
        self.now = datetime.now(timezone.utc)
        self.original = {'id': 'event', 'etag': 'v1', 'summary': 'Original',
            'updated': (self.now - timedelta(days=1)).isoformat(),
            'start': {'date': '2030-01-01'}, 'end': {'date': '2030-01-02'}}
        google.apply_remote(self.db, self.calendar, self.original)
        self.db.commit()
        self.item = self.db.query(PlannerItem).one()

    def edit(self, stamp=None, delete=False):
        path = f'/api/tasks/{self.item.id}'
        response = (self.client.delete(f'{path}?revision={self.item.revision}') if delete else
                    self.client.patch(path, json={'revision': self.item.revision, 'title': 'Local'}))
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.item.updated_at = (stamp or self.now).isoformat()
        self.db.commit()

    def remote(self, stamp=None, **values):
        return {**self.original, 'etag': 'v2', 'summary': 'Google',
                'updated': (stamp or self.now + timedelta(minutes=1)).isoformat(), **values}

    def apply(self, event):
        google.apply_remote(self.db, self.calendar, event)
        self.db.commit()
        self.db.expire_all()
        self.assertIsNone(self.db.query(PlannerExternalLink).first().conflict if self.db.query(PlannerExternalLink).first() else None)

    def test_google_newer_wins_and_removes_queued_local_edit(self):
        self.edit()
        self.apply(self.remote())
        self.assertEqual(self.item.title, 'Google')
        self.assertEqual(self.item.updated_at, self.remote()['updated'])
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_local_newer_uses_fresh_etag_and_pushes_without_duplicate(self):
        self.edit()
        remote = self.remote(self.now - timedelta(minutes=1))
        self.apply(remote)
        self.assertEqual(self.item.title, 'Local')
        self.assertEqual(self.db.query(PlannerExternalLink).one().etag, 'v2')
        async def write(method, path, **kwargs):
            self.assertEqual(method, 'PATCH')
            self.assertEqual(kwargs['headers']['If-Match'], 'v2')
            self.assertEqual(kwargs['json']['summary'], 'Local')
            return {**remote, **kwargs['json'], 'etag': 'v3'}
        asyncio.run(google.push_job(self.db, SimpleNamespace(request=write), self.calendar, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)
        self.assertEqual(self.db.query(PlannerItem).count(), 1)

    def test_simultaneous_identical_changes_need_no_write(self):
        self.edit()
        self.apply(self.remote(summary='Local'))
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_unchanged_google_data_keeps_local_edit_despite_new_etag(self):
        self.edit()
        self.apply(self.remote(summary='Original'))
        self.assertEqual(self.item.title, 'Local')
        self.assertEqual(self.db.query(PlannerSyncJob).one().state, 'pending')

    def test_both_deleted_drop_queue_and_link(self):
        self.edit(delete=True)
        self.apply(self.remote(status='cancelled'))
        self.assertTrue(self.item.deleted_at)
        self.assertEqual(self.db.query(PlannerExternalLink).count(), 0)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_newer_google_delete_does_not_resurrect_old_local_edit(self):
        self.edit()
        self.apply(self.remote(status='cancelled'))
        self.assertTrue(self.item.deleted_at)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_newer_local_edit_recreates_older_google_deletion(self):
        self.edit()
        self.apply(self.remote(self.now - timedelta(minutes=1), status='cancelled'))
        self.assertIsNone(self.item.deleted_at)
        self.assertEqual(self.db.query(PlannerExternalLink).count(), 0)
        self.assertEqual(self.db.query(PlannerSyncJob).one().revision, self.item.revision)

    def test_newer_google_edit_restores_older_local_deletion(self):
        self.edit(delete=True)
        self.apply(self.remote())
        self.assertIsNone(self.item.deleted_at)
        self.assertEqual(self.item.title, 'Google')
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_newer_local_deletion_stays_queued(self):
        self.edit(delete=True)
        self.apply(self.remote(self.now - timedelta(minutes=1)))
        self.assertTrue(self.item.deleted_at)
        self.assertEqual(self.db.query(PlannerSyncJob).one().state, 'pending')

    def test_timestamp_offset_and_equal_time_are_deterministic(self):
        self.edit()
        event = self.remote(self.now)
        event['updated'] = self.now.astimezone(timezone(timedelta(hours=3))).isoformat()
        self.apply(event)
        self.assertEqual(self.item.title, 'Google')

    def test_missing_delete_timestamp_keeps_deletion(self):
        self.edit()
        self.apply(self.remote(status='cancelled', updated=None))
        self.assertTrue(self.item.deleted_at)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_stale_legacy_conflict_is_rechecked_even_on_hidden_calendar(self):
        self.edit(delete=True)
        link = self.db.query(PlannerExternalLink).one()
        link.conflict = json.dumps(self.remote(summary='Stale'))
        self.db.query(PlannerSyncJob).one().state = 'conflict'
        self.calendar.managed, self.calendar.visible, self.calendar.writable = 0, 0, 1
        self.db.commit()
        api = SimpleNamespace(request=AsyncMock(return_value=self.remote(status='cancelled')), close=AsyncMock())
        with patch.object(google, 'SessionLocal', self.sessions), patch.object(google, 'access_token', AsyncMock(return_value='fake')), patch.object(google, 'GoogleAPI', return_value=api):
            self.assertEqual(asyncio.run(google.sync_google(force=True))['state'], 'connected')
        self.db.expire_all()
        self.assertEqual(self.db.query(PlannerExternalLink).count(), 0)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)
        api.request.assert_awaited_once()

    def test_http_412_reloads_then_retries_local_newer_without_blocking(self):
        self.edit()
        remote = self.remote(self.now - timedelta(minutes=1))
        api = SimpleNamespace(request=AsyncMock(side_effect=[google.GoogleError(412), remote]))
        asyncio.run(google.push_job(self.db, api, self.calendar, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(self.db.query(PlannerSyncJob).one().state, 'pending')
        self.assertEqual(self.db.query(PlannerExternalLink).one().etag, 'v2')
        self.assertIsNone(self.db.query(PlannerExternalLink).one().pending_snapshot)

    def test_import_preserves_remote_modification_time(self):
        self.assertEqual(self.item.updated_at, self.original['updated'])

    def test_import_wins_when_permissions_become_readonly(self):
        self.edit()
        self.item.read_only = 1
        self.calendar.managed, self.calendar.writable = 0, 0
        self.db.commit()
        self.apply(self.remote(self.now - timedelta(minutes=1)))
        self.assertEqual(self.item.title, 'Google')
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)
