import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx

from sqlalchemy import create_engine, inspect, text

from test_task_planner import PlannerFixture
from task_models import PlannerConnection, PlannerItem, PlannerSyncJob
from services.planner.google_errors import safe_google_error
from services.planner import google_sync as google
from services.planner.schema import ensure_planner_migrations
from routers import planner_google


class PlannerRecoveryTests(PlannerFixture):
    def test_manual_sync_refreshes_calendar_names_and_access_before_syncing_events(self):
        calendar = self.connect(managed=False)
        calendar.visible = 0
        self.db.get(PlannerConnection, 'account-1').events_write = 1
        self.db.commit()
        api = SimpleNamespace(pages=AsyncMock(return_value=([{
            'id': calendar.remote_id, 'summary': 'Нова назва', 'accessRole': 'writer',
        }], None)), close=AsyncMock())

        async def sync_events(force=False):
            self.db.refresh(calendar)
            self.assertEqual((calendar.name, calendar.writable, calendar.visible), ('Нова назва', 1, 0))
            api.close.assert_awaited_once()
            self.assertTrue(force)
            return {'state': 'connected'}

        with patch.object(planner_google, 'access_token', AsyncMock(return_value='fake')), \
             patch.object(planner_google, 'GoogleAPI', return_value=api), \
             patch.object(planner_google, 'sync_google', side_effect=sync_events) as sync:
            response = self.client.post('/api/planner/google/sync')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['state'], 'connected')
        sync.assert_awaited_once_with(force=True)

    def test_manual_sync_stops_if_calendar_discovery_fails(self):
        self.connect()
        api = SimpleNamespace(pages=AsyncMock(side_effect=google.GoogleError(503)), close=AsyncMock())
        with patch.object(planner_google, 'access_token', AsyncMock(return_value='fake')), \
             patch.object(planner_google, 'GoogleAPI', return_value=api), \
             patch.object(planner_google, 'sync_google', AsyncMock()) as sync, patch('logger.log_event'):
            response = self.client.post('/api/planner/google/sync')
        self.assertGreaterEqual(response.status_code, 400)
        sync.assert_not_awaited()
        api.close.assert_awaited_once()

    def test_discovery_restores_marked_app_calendar_without_creating_duplicate(self):
        calendar = self.connect(managed=False)
        calendar.visible = 0
        self.db.commit()
        api = SimpleNamespace(pages=AsyncMock(return_value=([{
            'id': calendar.remote_id, 'summary': 'School Manager', 'accessRole': 'owner',
            'description': planner_google.calendar_marker('google-sub'),
        }], None)), close=AsyncMock(), request=AsyncMock())
        with patch.object(planner_google, 'access_token', AsyncMock(return_value='fake')), \
             patch.object(planner_google, 'GoogleAPI', return_value=api), patch('logger.log_event'):
            response = self.client.post('/api/planner/google/calendars')
        self.assertEqual(response.status_code, 200, response.text)
        self.db.refresh(calendar)
        self.assertEqual((calendar.managed, calendar.visible, calendar.writable), (1, 1, 1))
        self.assertEqual(self.db.query(type(calendar)).count(), 1)
        api.request.assert_not_awaited()
        api.close.assert_awaited_once()

    def test_discovery_does_not_adopt_calendar_by_name_or_other_owner_marker(self):
        calendar = self.connect(managed=False)
        for description, role in [(None, 'owner'), ('School Manager planner wrong-account', 'owner'),
                                  (planner_google.calendar_marker('google-sub'), 'writer')]:
            with self.subTest(description=description, role=role):
                api = SimpleNamespace(pages=AsyncMock(return_value=([{
                    'id': calendar.remote_id, 'summary': 'School Manager', 'accessRole': role,
                    'description': description,
                }], None)), close=AsyncMock())
                with patch.object(planner_google, 'access_token', AsyncMock(return_value='fake')), \
                     patch.object(planner_google, 'GoogleAPI', return_value=api):
                    self.assertEqual(self.client.post('/api/planner/google/calendars').status_code, 200)
                self.db.refresh(calendar)
                self.assertFalse(calendar.managed)

    def test_oauth_cancellation_notice_is_separate_from_connected_account(self):
        self.connect()
        fake_oauth = SimpleNamespace(state='idle', error=None, notice='Вхід у Google не завершено')
        with patch.object(planner_google, 'oauth', fake_oauth):
            response = self.client.get('/api/planner/google/status').json()
        self.assertEqual(response['connection']['state'], 'connected')
        self.assertIsNone(response['oauth_error'])
        self.assertEqual(response['oauth_notice'], fake_oauth.notice)

    def test_connection_failure_diagnostics_include_safe_cause_codes(self):
        error = httpx.ConnectError('PRIVATE token=SECRET', request=httpx.Request('GET', 'https://example.test/?token=SECRET'))
        error.__cause__ = OSError(10061, 'PRIVATE details')
        detail = safe_google_error(error)
        self.assertIn('httpx.ConnectError', detail)
        self.assertIn('errno=10061', detail)
        self.assertNotIn('SECRET', detail)
        self.assertNotIn('PRIVATE', detail)

    def test_diagnostic_export_includes_google_connection_and_calendar_state(self):
        self.connect()
        from routers import system
        from services.planner import google_auth
        fake_oauth = SimpleNamespace(state='idle', error=None, stage=None, notice='Вхід не завершено')
        with patch.object(system, 'SessionLocal', self.sessions), \
             patch.object(system, 'get_runtime_data_dir', return_value=self.tmp.name), \
             patch.object(google_auth, 'oauth', fake_oauth):
            content = system._build_diagnostic_log()
        self.assertIn('Google Calendar State', content)
        self.assertIn('connection_state: connected', content)
        self.assertIn('managed: 1', content)
        self.assertIn('oauth_notice: Вхід не завершено', content)

    def test_reconnect_reuses_account_and_resets_failed_attempts(self):
        self.connect()
        connection = self.db.get(PlannerConnection, 'account-1')
        connection.state, connection.sync_attempts = 'reauth', 6
        self.db.commit()
        with patch.object(planner_google, 'SessionLocal', self.sessions):
            asyncio.run(planner_google.connected({'sub': 'google-sub', 'email': 'fake@example.test'}))
        self.db.expire_all()
        self.assertEqual(connection.state, 'connected')
        self.assertEqual(connection.sync_attempts, 0)
        self.assertEqual(self.db.query(PlannerConnection).count(), 1)

    def test_backoff_after_six_failures_waits_then_recovers_automatically(self):
        self.connect()
        api = SimpleNamespace(close=AsyncMock())
        with patch.object(google, 'SessionLocal', self.sessions), patch.object(google, 'access_token', AsyncMock(return_value='fake')), patch.object(google, 'GoogleAPI', return_value=api), patch.object(google, 'pull_calendar', AsyncMock(side_effect=google.GoogleError(429))) as pull, patch('logger.log_event'):
            for attempt in range(1, 7):
                self.assertEqual(asyncio.run(google.sync_google(force=True))['state'], 'error')
                self.db.expire_all()
                connection = self.db.get(PlannerConnection, 'account-1')
                self.assertEqual(connection.sync_attempts, attempt)
                self.assertGreater(datetime.fromisoformat(connection.next_sync_at), datetime.now(timezone.utc))
            self.assertEqual(connection.state, 'error')
            asyncio.run(google.sync_google())
            self.assertEqual(pull.await_count, 6)
            pull.side_effect = None
            connection.next_sync_at = '2000-01-01T00:00:00+00:00'
            self.db.commit()
            self.assertEqual(asyncio.run(google.sync_google())['state'], 'connected')
            self.db.expire_all()
            self.assertEqual(connection.sync_attempts, 0)
        self.assertEqual(api.close.await_count, 7)

    def test_manual_retry_ignores_backoff(self):
        self.connect()
        connection = self.db.get(PlannerConnection, 'account-1')
        connection.state, connection.next_sync_at = 'error', '2099-01-01T00:00:00+00:00'
        self.db.commit()
        api = SimpleNamespace(close=AsyncMock())
        with patch.object(google, 'SessionLocal', self.sessions), patch.object(google, 'access_token', AsyncMock(return_value='fake')), \
             patch.object(google, 'GoogleAPI', return_value=api), patch.object(google, 'pull_calendar', AsyncMock()):
            self.assertEqual(asyncio.run(google.sync_google(force=True))['state'], 'connected')

    def test_expired_google_authorization_pauses_requests(self):
        self.connect()
        with patch.object(google, 'SessionLocal', self.sessions), patch.object(google, 'access_token', AsyncMock(side_effect=google.HTTPException(401))) as token, patch('logger.log_event'):
            asyncio.run(google.sync_google())
            self.db.expire_all()
            self.assertEqual(self.db.get(PlannerConnection, 'account-1').state, 'reauth')
            self.assertEqual(asyncio.run(google.sync_google(force=True))['state'], 'reauth')
            token.assert_awaited_once()

    def test_refresh_server_error_is_logged_with_status_without_token_contents(self):
        self.connect()
        error = httpx.HTTPStatusError('PRIVATE RESPONSE', request=httpx.Request('POST', 'https://oauth2.googleapis.com/token'),
                                     response=httpx.Response(503))
        with patch.object(google, 'SessionLocal', self.sessions), \
             patch.object(google, 'access_token', AsyncMock(side_effect=error)), patch('logger.log_event') as log:
            self.assertEqual(asyncio.run(google.sync_google())['state'], 'error')
        self.assertIn('HTTP 503', str(log.call_args))
        self.assertNotIn('PRIVATE', str(log.call_args))

    def test_missing_permission_is_not_presented_as_a_rate_limit(self):
        self.connect()
        api = SimpleNamespace(close=AsyncMock())
        with patch.object(google, 'SessionLocal', self.sessions), patch.object(google, 'access_token', AsyncMock(return_value='fake')), \
             patch.object(google, 'GoogleAPI', return_value=api), \
             patch.object(google, 'pull_calendar', AsyncMock(side_effect=google.GoogleError(403, 'Forbidden'))), patch('logger.log_event'):
            result = asyncio.run(google.sync_google())
        self.assertIn('Оновіть дозволи', result['error'])

    def test_restored_task_cannot_move_to_new_google_account(self):
        calendar = self.connect()
        item = self.create(date='2030-01-01', google_enabled=True)
        # Simulate a confirmed remote deletion: its link is gone, ownership remains.
        self.client.delete(f'/api/tasks/{item["id"]}?revision=1')
        connection = self.db.get(PlannerConnection, 'account-1')
        connection.state = 'disconnected'
        self.db.add(PlannerConnection(id='account-2', account_id='other-sub'))
        self.db.commit()
        self.client.post(f'/api/tasks/{item["id"]}/restore', json={'revision': 2})
        self.db.expire_all()
        self.assertEqual(self.db.get(PlannerItem, item['id']).google_connection_id, 'account-1')
        self.assertEqual(self.db.query(PlannerSyncJob).one().connection_id, 'account-1')
        calendar.connection_id = 'account-2'
        api = SimpleNamespace(request=AsyncMock())
        asyncio.run(google.push_job(self.db, api, calendar, self.db.query(PlannerSyncJob).one()))
        api.request.assert_not_awaited()

    def test_preview_schema_upgrade_preserves_rows_and_is_repeatable(self):
        engine = create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE planner_connections (id TEXT PRIMARY KEY, email TEXT)'))
                connection.execute(text("INSERT INTO planner_connections VALUES ('saved', 'test@example.test')"))
            ensure_planner_migrations(engine)
            ensure_planner_migrations(engine)
            self.assertIn('sync_attempts', {c['name'] for c in inspect(engine).get_columns('planner_connections')})
            with engine.connect() as connection:
                self.assertEqual(tuple(connection.execute(text('SELECT * FROM planner_connections')).one()), ('saved', 'test@example.test', 0, 0))
        finally:
            engine.dispose()
