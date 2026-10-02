import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
import models
from task_models import PlannerCalendar, PlannerConnection, PlannerExternalLink, PlannerItem, PlannerReminder, PlannerSyncJob
from routers import tasks, planner_google
from services.planner import google_sync as google, reminders
from services.planner.items import local_datetime, utc_now


class PlannerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{self.tmp.name}/planner.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()
        app = FastAPI()
        app.include_router(tasks.router, prefix='/api')
        app.include_router(planner_google.router, prefix='/api')
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def create(self, **values):
        result = self.client.post('/api/tasks', json={'title': 'Підготовка до уроку', **values})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def connect(self, managed=True):
        connection = PlannerConnection(id='account-1', account_id='google-sub', email='fake@example.test')
        calendar = PlannerCalendar(connection_id=connection.id, remote_id='calendar-id', name='School Manager', managed=int(managed), visible=1)
        self.db.add_all([connection, calendar]); self.db.commit()
        return calendar


class TaskApiTests(PlannerFixture):
    def test_create_idempotent_and_survives_new_session(self):
        identity = str(uuid4())
        a, b = self.create(request_id=identity), self.create(request_id=identity)
        self.assertEqual(a['id'], b['id'])
        with self.sessions() as db:
            self.assertEqual(db.query(PlannerItem).count(), 1)
            self.assertEqual(db.get(PlannerItem, a['id']).title, a['title'])

    def test_revision_conflict_preserves_latest(self):
        item = self.create()
        url = '/api/tasks/' + item['id']
        self.assertEqual(self.client.patch(url, json={'revision': 1, 'title': 'Правка'}).status_code, 200)
        self.assertEqual(self.client.patch(url, json={'revision': 1, 'title': 'Стара правка'}).status_code, 409)
        self.assertEqual(self.client.get(url).json()['title'], 'Правка')

    def test_no_date_event_rejected(self):
        self.assertEqual(self.client.post('/api/tasks', json={'title': 'Урок', 'kind': 'event'}).status_code, 422)

    def test_invalid_and_null_patch_do_not_crash(self):
        item = self.create(date='2026-09-26')
        for values in [{'title': None}, {'date': 'not-date'}, {'timezone': 'made-up'}, {'description': None}]:
            self.assertEqual(self.client.patch('/api/tasks/' + item['id'], json={'revision': 1, **values}).status_code, 422)

    def test_all_day_exclusive_end_and_filter(self):
        item = self.create(date='2026-09-26', end_date='2026-09-28')
        self.assertEqual(item['end'], '2026-09-29')
        result = self.client.get('/api/tasks?start=2026-09-28&end=2026-09-29').json()
        self.assertEqual(result['total'], 1)
        self.assertEqual(self.client.get('/api/tasks?start=2026-09-29&end=2026-09-30').json()['total'], 0)

    def test_overnight_move_preserves_end_day(self):
        item = self.create(date='2026-09-26', time='23:30', end_date='2026-09-27', end_time='01:00')
        result = self.client.patch('/api/tasks/' + item['id'], json={'revision': 1, 'date': '2026-09-29'}).json()
        self.assertEqual(result['end_date'], '2026-09-30')
        self.assertEqual(result['end_time'], '01:00')

    def test_dst_missing_and_ambiguous(self):
        with self.assertRaises(Exception):
            local_datetime('2026-03-29', '03:30', 'Europe/Kyiv')
        with self.assertRaises(Exception):
            local_datetime('2026-10-25', '03:30', 'Europe/Kyiv')
        first = local_datetime('2026-10-25', '03:30', 'Europe/Kyiv', 0)
        second = local_datetime('2026-10-25', '03:30', 'Europe/Kyiv', 1)
        self.assertEqual(second - first, timedelta(hours=1))

    def test_task_done_but_event_not_completed(self):
        item = self.create(date='2026-09-26')
        self.client.patch('/api/tasks/' + item['id'], json={'revision': 1, 'status': 'done'})
        self.assertEqual(self.client.get('/api/tasks?bucket=all').json()['total'], 0)
        self.assertEqual(self.client.get('/api/tasks?bucket=all&completed=true').json()['total'], 1)
        self.assertEqual(self.client.post('/api/tasks', json={'title': 'Урок', 'date': '2026-09-26', 'kind': 'event', 'status': 'done'}).status_code, 422)

    def test_trash_restore_and_linked_preparation_preserved(self):
        parent = self.create(kind='event', date='2026-09-26')
        child = self.create(parent_id=parent['id'])
        deleted = self.client.delete(f'/api/tasks/{parent["id"]}?revision=1').json()
        self.assertIsNotNone(deleted['deleted_at'])
        self.assertEqual(self.client.get('/api/tasks?bucket=undated').json()['items'][0]['id'], child['id'])
        self.assertEqual(self.client.get('/api/tasks?bucket=trash').json()['total'], 1)
        restored = self.client.post(f'/api/tasks/{parent["id"]}/restore', json={'revision': 2}).json()
        self.assertIsNone(restored['deleted_at'])

    def test_read_only_api_enforcement(self):
        item = self.create(date='2026-09-26')
        saved = self.db.get(PlannerItem, item['id']); saved.read_only = 1; self.db.commit()
        self.assertEqual(self.client.patch('/api/tasks/' + item['id'], json={'revision': 1, 'title': 'Не можна'}).status_code, 403)
        self.assertEqual(self.client.delete(f'/api/tasks/{item["id"]}?revision=1').status_code, 403)

    def test_reminder_shift_and_completion_cancel(self):
        item = self.create(date='2030-09-26', time='14:00')
        url = '/api/tasks/' + item['id']
        reminded = self.client.post(url + '/reminders', json={'revision': 1, 'date': '2030-09-26', 'time': '13:00'}).json()
        self.assertEqual(len(reminded['reminders']), 1)
        moved = self.client.patch(url, json={'revision': 1, 'date': '2030-09-27'}).json()
        self.assertEqual(moved['reminders'][0]['remind_at'], '2030-09-27T10:00:00+00:00')
        done = self.client.patch(url, json={'revision': 2, 'status': 'done'}).json()
        self.assertEqual(done['reminders'][0]['state'], 'cancelled')

    def test_batch_500_items_uses_constant_query_count(self):
        now = utc_now()
        self.db.add_all([PlannerItem(title=f'Задача {n}', created_at=now, updated_at=now) for n in range(500)])
        self.db.commit()
        statements = []
        def record(*args): statements.append(args[2])
        event.listen(self.engine, 'before_cursor_execute', record)
        try:
            response = self.client.get('/api/tasks?bucket=undated').json()
        finally:
            event.remove(self.engine, 'before_cursor_execute', record)
        self.assertEqual(len(response['items']), 500)
        self.assertLessEqual(len(statements), 6)

    def test_queue_bound_to_google_account(self):
        calendar = self.connect()
        item = self.create(date='2030-01-01', google_enabled=True)
        self.assertEqual(self.db.query(PlannerSyncJob).filter_by(item_id=item['id']).one().connection_id, calendar.connection_id)


class GoogleSyncTests(PlannerFixture):
    def setUp(self):
        super().setUp()
        self.calendar = self.connect()

    def remote(self, identity='event1', **values):
        return {'id': identity, 'etag': 'v1', 'summary': 'Урок Google', 'description': '', 'start': {'date': '2026-09-26'}, 'end': {'date': '2026-09-27'}, **values}

    def test_import_update_no_duplicates(self):
        google.apply_remote(self.db, self.calendar, self.remote()); self.db.commit()
        google.apply_remote(self.db, self.calendar, self.remote()); self.db.commit()
        google.apply_remote(self.db, self.calendar, self.remote(etag='v2', summary='Нова тема')); self.db.commit()
        self.assertEqual(self.db.query(PlannerItem).count(), 1)
        self.assertEqual(self.db.query(PlannerItem).one().title, 'Нова тема')

    def test_remote_and_local_conflict_keeps_both(self):
        google.apply_remote(self.db, self.calendar, self.remote()); self.db.commit()
        item = self.db.query(PlannerItem).one()
        self.client.patch('/api/tasks/' + item.id, json={'revision': 1, 'title': 'Локальна тема'})
        self.db.expire_all()
        google.apply_remote(self.db, self.calendar, self.remote(etag='v2', summary='Тема з телефона')); self.db.commit()
        self.assertEqual(self.db.get(PlannerItem, item.id).title, 'Локальна тема')
        self.assertEqual(json.loads(self.db.query(PlannerExternalLink).one().conflict)['summary'], 'Тема з телефона')

    def test_external_recurrence_is_readonly(self):
        google.apply_remote(self.db, self.calendar, self.remote(recurringEventId='series')); self.db.commit()
        self.assertEqual(self.db.query(PlannerItem).one().read_only, 1)

    def test_other_calendar_import_is_readonly(self):
        self.calendar.managed = 0
        google.apply_remote(self.db, self.calendar, self.remote()); self.db.commit()
        self.assertEqual(self.db.query(PlannerItem).one().read_only, 1)

    def test_lost_post_ack_uses_same_event_id_and_one_link(self):
        item = self.create(date='2030-01-01', google_enabled=True)
        job = self.db.query(PlannerSyncJob).one()
        ids = []
        async def request(method, path, **kwargs):
            ids.append(kwargs['json']['id'])
            if len(ids) == 1:
                raise TimeoutError()
            return {**kwargs['json'], 'etag': 'v1'}
        api = SimpleNamespace(request=request)
        with self.assertRaises(TimeoutError): asyncio.run(google.push_job(self.db, api, self.calendar, job))
        self.db.rollback()
        asyncio.run(google.push_job(self.db, api, self.calendar, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.db.query(PlannerExternalLink).count(), 1)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_queue_not_sent_to_other_account(self):
        self.create(date='2030-01-01', google_enabled=True)
        other = PlannerCalendar(connection_id='different', remote_id='other', name='Other', managed=1)
        api = SimpleNamespace(request=AsyncMock())
        asyncio.run(google.push_job(self.db, api, other, self.db.query(PlannerSyncJob).one()))
        api.request.assert_not_awaited()

    def test_410_resync_preserves_local_pending_changes(self):
        self.create(date='2030-01-01', google_enabled=True)
        self.calendar.sync_token, self.calendar.sync_format = 'expired', 1; self.db.commit()
        api = SimpleNamespace(pages=AsyncMock(side_effect=[google.GoogleError(410), ([], 'new-token')]))
        asyncio.run(google.pull_calendar(self.db, api, self.calendar))
        self.assertEqual(self.db.query(PlannerItem).count(), 1)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 1)
        self.assertEqual(self.calendar.sync_token, 'new-token')

    def test_pagination_not_advanced_on_second_page_error(self):
        self.calendar.sync_token, self.calendar.sync_format = 'before', 1; self.db.commit()
        api = google.GoogleAPI('fake')
        api.request = AsyncMock(side_effect=[{'items': [self.remote()], 'nextPageToken': 'page2'}, google.GoogleError(500)])
        try:
            with self.assertRaises(google.GoogleError): asyncio.run(google.pull_calendar(self.db, api, self.calendar))
            self.assertEqual(self.calendar.sync_token, 'before')
            self.assertEqual(self.db.query(PlannerItem).count(), 0)
        finally: asyncio.run(api.close())


class ReminderTests(PlannerFixture):
    def test_local_notification_once(self):
        item = self.create()
        now = datetime.now(timezone.utc)
        self.db.add(PlannerReminder(item_id=item['id'], channel='system', remind_at=(now - timedelta(seconds=10)).isoformat(), updated_at=utc_now()))
        self.db.commit()
        with patch.object(reminders, 'SessionLocal', self.sessions), patch.object(reminders, 'show_system_notification', return_value=True) as notify:
            asyncio.run(reminders.process_reminders()); asyncio.run(reminders.process_reminders())
        self.assertEqual(notify.call_count, 1)

    def test_sleep_one_aggregate_notification(self):
        item = self.create()
        now = datetime.now(timezone.utc)
        self.db.add_all([PlannerReminder(item_id=item['id'], channel='system', remind_at=(now - timedelta(hours=2, minutes=n)).isoformat(), updated_at=utc_now()) for n in range(3)])
        self.db.commit()
        with patch.object(reminders, 'SessionLocal', self.sessions), patch.object(reminders, 'show_system_notification', return_value=True) as notify:
            asyncio.run(reminders.process_reminders()); asyncio.run(reminders.process_reminders())
        self.assertEqual(notify.call_count, 1)
        self.assertIn('3', notify.call_args.args[1])

    def test_completed_does_not_notify(self):
        item = self.create(status='done')
        self.db.add(PlannerReminder(item_id=item['id'], channel='system', remind_at=utc_now(), updated_at=utc_now())); self.db.commit()
        with patch.object(reminders, 'SessionLocal', self.sessions), patch.object(reminders, 'show_system_notification') as notify:
            asyncio.run(reminders.process_reminders())
        notify.assert_not_called()
