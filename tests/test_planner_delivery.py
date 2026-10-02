from datetime import datetime, timedelta, timezone
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_task_planner import PlannerFixture
from task_models import PlannerCalendar, PlannerConnection, PlannerExternalLink, PlannerItem, PlannerReminder, PlannerSyncJob
from services.planner import google_sync as google, reminders
from routers.planner_google import update_calendar_access
from services.planner.items import utc_now


class GoogleAcknowledgementTests(PlannerFixture):
    def test_series_delete_cancels_cached_occurrences_only(self):
        cal = self.connect()
        for n in range(2):
            google.apply_remote(self.db, cal, {'id': f'occurrence-{n}', 'etag': 'v1', 'recurringEventId': 'series', 'start': {'date': f'2030-01-0{n+1}'}, 'end': {'date': f'2030-01-0{n+2}'}})
            self.db.commit()
        local = self.create(title='Моя підготовка')
        google.apply_remote(self.db, cal, {'id': 'series', 'etag': 'v2', 'status': 'cancelled'})
        self.db.commit()
        self.assertEqual(self.db.query(PlannerItem).filter(PlannerItem.deleted_at.isnot(None)).count(), 2)
        self.assertIsNone(self.db.get(PlannerItem, local['id']).deleted_at)

    def test_google_delete_restore_generates_fresh_remote_id(self):
        cal = self.connect()
        local = self.create(date='2030-01-01', google_enabled=True)
        async def request(method, path, **kwargs):
            return {**kwargs.get('json', {}), 'etag': 'v1'}
        api = SimpleNamespace(request=request)
        asyncio.run(google.push_job(self.db, api, cal, self.db.query(PlannerSyncJob).one()))
        original = self.db.query(PlannerExternalLink).one().event_id
        self.client.delete(f'/api/tasks/{local["id"]}?revision=1')
        self.db.expire_all()
        asyncio.run(google.push_job(self.db, api, cal, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(self.db.query(PlannerExternalLink).count(), 0)
        self.client.post(f'/api/tasks/{local["id"]}/restore', json={'revision': 2})
        self.db.expire_all()
        asyncio.run(google.push_job(self.db, api, cal, self.db.query(PlannerSyncJob).one()))
        self.assertNotEqual(original, self.db.query(PlannerExternalLink).one().event_id)

    def test_lost_write_then_pull_acknowledges_without_duplicate(self):
        cal = self.connect()
        item = self.create(date='2030-01-01', time='12:00', google_enabled=True)
        captured = {}
        async def write(method, path, **kwargs):
            captured.update(kwargs['json'])
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            asyncio.run(google.push_job(self.db, SimpleNamespace(request=write), cal, self.db.query(PlannerSyncJob).one()))
        self.db.rollback()
        captured['etag'] = 'received'
        # Google is free to return an equivalent timestamp with its timezone offset.
        captured['start']['dateTime'] = '2030-01-01T12:00:00+02:00'
        captured['end']['dateTime'] = '2030-01-01T12:30:00+02:00'
        google.apply_remote(self.db, cal, captured); self.db.commit()
        self.assertEqual(self.db.query(PlannerItem).count(), 1)
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)
        self.assertIsNone(self.db.query(PlannerExternalLink).one().conflict)

    def test_edit_during_write_remains_queued(self):
        cal = self.connect()
        item = self.create(date='2030-01-01', google_enabled=True)
        async def write(method, path, **kwargs):
            response = self.client.patch('/api/tasks/' + item['id'], json={'revision': 1, 'title': 'Нова правка під час синхронізації'})
            self.assertEqual(response.status_code, 200)
            return {**kwargs['json'], 'etag': 'received'}
        asyncio.run(google.push_job(self.db, SimpleNamespace(request=write), cal, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(self.db.query(PlannerSyncJob).one().revision, 2)
        self.assertEqual(self.db.get(PlannerItem, item['id']).title, 'Нова правка під час синхронізації')

    def test_readonly_calendar_not_written_even_with_job(self):
        cal = self.connect()
        item = self.create(date='2030-01-01', google_enabled=True)
        saved = self.db.get(PlannerItem, item['id']); saved.read_only = 1; cal.managed = 0; self.db.commit()
        api = SimpleNamespace(request=AsyncMock())
        asyncio.run(google.push_job(self.db, api, cal, self.db.query(PlannerSyncJob).one()))
        api.request.assert_not_awaited()

    def test_writable_external_event_edits_only_changed_fields(self):
        cal = self.connect(managed=False)
        cal.writable, cal.access_role = 1, 'writer'
        self.db.commit()
        original = {'id': 'foreign-event', 'etag': 'v1', 'summary': 'Урок',
            'start': {'date': '2030-01-01'}, 'end': {'date': '2030-01-02'},
            'reminders': {'useDefault': True}, 'extendedProperties': {'private': {'otherApp': 'keep'}},
            'attendees': [{'email': 'guest@example.com', 'responseStatus': 'accepted'}]}
        google.apply_remote(self.db, cal, original); self.db.commit()
        item = self.db.query(PlannerItem).one()
        self.assertFalse(item.read_only)
        result = self.client.patch('/api/tasks/' + item.id, json={'revision': 1, 'title': 'Новий урок'})
        self.assertEqual(result.status_code, 200, result.text)
        writes = []
        async def write(method, path, **kwargs):
            writes.append((method, path, kwargs['json']))
            return {**original, **kwargs['json'], 'etag': 'v2'}
        self.db.expire_all()
        asyncio.run(google.push_job(self.db, SimpleNamespace(request=write), cal, self.db.query(PlannerSyncJob).one()))
        self.assertEqual(writes[0][0], 'PATCH')
        self.assertIn('/foreign-event', writes[0][1])
        self.assertEqual(writes[0][2], {'summary': 'Новий урок'})
        self.assertEqual(self.db.query(PlannerSyncJob).count(), 0)

    def test_target_calendar_write_permission_enforced(self):
        cal = self.connect(managed=False)
        response = self.client.post('/api/tasks', json={'title': 'Урок', 'date': '2030-01-01',
            'google_enabled': True, 'google_calendar_id': cal.id})
        self.assertEqual(response.status_code, 403)
        cal.writable, cal.access_role = 1, 'owner'
        self.db.commit()
        response = self.client.post('/api/tasks', json={'title': 'Урок', 'date': '2030-01-01',
            'google_enabled': True, 'google_calendar_id': cal.id})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['google_calendar_id'], cal.id)

    def test_calendar_change_rejected_for_linked_event(self):
        cal = self.connect(managed=False)
        cal.writable = 1
        second = PlannerCalendar(connection_id=cal.connection_id, remote_id='second', name='Other', visible=1, writable=1)
        self.db.add(second); self.db.commit()
        google.apply_remote(self.db, cal, {'id': 'event', 'etag': 'v1', 'summary': 'Урок',
            'start': {'date': '2030-01-01'}, 'end': {'date': '2030-01-02'}})
        self.db.commit()
        item = self.db.query(PlannerItem).one()
        response = self.client.patch('/api/tasks/' + item.id, json={'revision': 1, 'google_calendar_id': second.id})
        self.assertEqual(response.status_code, 422)

    def test_new_event_is_sent_to_selected_calendar(self):
        managed = self.connect()
        other = PlannerCalendar(connection_id=managed.connection_id, remote_id='chosen-calendar',
            name='Lessons', visible=1, writable=1)
        self.db.add(other); self.db.commit()
        item = self.create(title='Нова подія', date='2030-01-01', kind='event',
            google_enabled=True, google_calendar_id=other.id)
        writes = []
        async def request(method, path, **kwargs):
            writes.append((method, path, kwargs['json']))
            return {**kwargs['json'], 'etag': 'v1'}
        api = SimpleNamespace(request=request, close=AsyncMock())
        with (patch.object(google, 'SessionLocal', self.sessions),
              patch.object(google, 'access_token', AsyncMock(return_value='fake')),
              patch.object(google, 'GoogleAPI', return_value=api),
              patch.object(google, 'pull_calendar', AsyncMock())):
            asyncio.run(google.sync_google(force=True))
        self.assertEqual(len(writes), 1)
        self.assertIn('chosen-calendar', writes[0][1])
        self.assertNotIn('reminders', writes[0][2])
        self.assertEqual(self.db.query(PlannerExternalLink).one().calendar_id, other.id)

    def test_new_scope_unlocks_existing_import_without_new_etag(self):
        cal = self.connect(managed=False)
        original = {'id': 'existing', 'etag': 'v1', 'summary': 'Урок',
            'start': {'date': '2030-01-01'}, 'end': {'date': '2030-01-02'}}
        google.apply_remote(self.db, cal, original); self.db.commit()
        item = self.db.query(PlannerItem).one()
        self.assertTrue(item.read_only)
        update_calendar_access(self.db, cal, 'writer', True)
        self.db.commit()
        self.assertFalse(item.read_only)
        self.assertTrue(item.google_enabled)
        google.apply_remote(self.db, cal, original); self.db.commit()
        self.assertFalse(item.read_only)

    def test_linked_event_can_be_edited_while_connection_needs_reauth(self):
        cal = self.connect(managed=False)
        cal.writable = 1
        google.apply_remote(self.db, cal, {'id': 'existing', 'etag': 'v1', 'summary': 'Урок',
            'start': {'date': '2030-01-01'}, 'end': {'date': '2030-01-02'}})
        self.db.commit()
        item = self.db.query(PlannerItem).one()
        self.db.query(PlannerConnection).one().state = 'reauth'
        self.db.commit()
        response = self.client.patch('/api/tasks/' + item.id, json={'revision': 1, 'title': 'Офлайн зміна'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(PlannerSyncJob).one().state, 'pending')


class TelegramReminderTests(PlannerFixture):
    def setUp(self):
        super().setUp()
        item = self.create(date='2030-01-01', time='12:00')
        self.item = self.db.get(PlannerItem, item['id'])
        self.reminder = PlannerReminder(item_id=item['id'], channel='telegram', remind_at='2030-01-01T09:00:00+00:00', updated_at=utc_now())
        self.db.add(self.reminder); self.db.commit()
        self.now = datetime(2030, 1, 1, 8, tzinfo=timezone.utc)
        self.client_tg = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(id=123)), resolve_peer=AsyncMock(return_value=object()), invoke=AsyncMock())
        self.manager = SimpleNamespace(is_connected=True, client=self.client_tg)

    def run_reminder(self):
        async def queued(label, action, **kw):
            return await action()
        with patch.object(reminders, 'pyrogram_manager', self.manager), patch.object(reminders.telegram_send_queue, 'run', side_effect=queued):
            asyncio.run(reminders.process_telegram(self.db, self.item, self.reminder, self.now))

    def test_uncertain_send_is_checked_before_retry(self):
        self.client_tg.invoke.side_effect = TimeoutError()
        self.run_reminder()
        self.assertEqual(self.reminder.state, 'uncertain')
        self.assertIsNotNone(self.reminder.random_id)
        self.client_tg.invoke.reset_mock(side_effect=True)
        self.client_tg.invoke.return_value = SimpleNamespace(messages=[])
        self.run_reminder()
        self.assertEqual(self.client_tg.invoke.call_count, 1)
        self.assertEqual(type(self.client_tg.invoke.call_args.args[0]).__name__, 'GetScheduledHistory')
        self.assertEqual(self.reminder.state, 'uncertain')

    def test_recovered_scheduled_message_reuses_id(self):
        self.reminder.state = 'uncertain'; self.reminder.random_id = '123'; self.db.commit()
        message = SimpleNamespace(id=77, message=reminders.reminder_text(self.item, self.reminder))
        self.client_tg.invoke.side_effect = [SimpleNamespace(messages=[message]), SimpleNamespace(updates=[])]
        self.run_reminder()
        self.assertEqual(self.reminder.scheduled_message_id, 77)
        self.assertEqual(self.reminder.state, 'scheduled')
        self.assertEqual(type(self.client_tg.invoke.call_args.args[0]).__name__, 'EditMessage')

    def test_cancel_known_message_and_other_account_protection(self):
        self.reminder.state = 'cancel_pending'; self.reminder.scheduled_message_id = 77
        self.reminder.account_id = '456'; self.db.commit()
        self.run_reminder()
        self.client_tg.invoke.assert_not_awaited()
        self.reminder.account_id = '123'; self.db.commit()
        self.client_tg.invoke.side_effect = [SimpleNamespace(messages=[SimpleNamespace(id=77, message='')]), SimpleNamespace(updates=[])]
        self.run_reminder()
        self.assertEqual(self.reminder.state, 'cancelled')
        self.assertEqual(type(self.client_tg.invoke.call_args.args[0]).__name__, 'DeleteScheduledMessages')

    def test_reminder_duplicate_and_reenable(self):
        url = '/api/tasks/' + self.item.id + '/reminders'
        body = {'revision': 1, 'channel': 'system', 'date': '2030-01-01', 'time': '10:00'}
        for _ in range(2):
            self.assertEqual(self.client.post(url, json=body).status_code, 200)
        rows = self.db.query(PlannerReminder).filter_by(channel='system').all()
        self.assertEqual(len(rows), 1)
        self.client.delete(url + '/' + rows[0].id)
        self.client.post(url, json=body)
        self.db.expire_all()
        self.assertEqual(self.db.query(PlannerReminder).filter_by(channel='system').one().state, 'pending')
