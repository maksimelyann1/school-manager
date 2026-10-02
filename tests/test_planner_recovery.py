import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, inspect, text

from test_task_planner import PlannerFixture
from task_models import PlannerConnection, PlannerItem, PlannerSyncJob
from services.planner import google_sync as google
from services.planner.schema import ensure_planner_migrations
from routers import planner_google


class PlannerRecoveryTests(PlannerFixture):
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

    def test_backoff_stops_after_six_failures_and_manual_retry_recovers(self):
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
            self.assertEqual(asyncio.run(google.sync_google(force=True))['state'], 'connected')
            self.db.expire_all()
            self.assertEqual(connection.sync_attempts, 0)
        self.assertEqual(api.close.await_count, 7)

    def test_expired_google_authorization_pauses_requests(self):
        self.connect()
        with patch.object(google, 'SessionLocal', self.sessions), patch.object(google, 'access_token', AsyncMock(side_effect=google.HTTPException(401))) as token, patch('logger.log_event'):
            asyncio.run(google.sync_google())
            self.db.expire_all()
            self.assertEqual(self.db.get(PlannerConnection, 'account-1').state, 'reauth')
            asyncio.run(google.sync_google())
            token.assert_awaited_once()

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
