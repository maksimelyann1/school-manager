import asyncio
from contextlib import ExitStack
import json
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

from test_task_planner import PlannerFixture
from services.planner import google_auth as auth
from task_models import PlannerItem, PlannerReminder
from services.planner.items import utc_now
import httpx


class OAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(auth, 'client_config', return_value={'client_id': 'fake.apps.googleusercontent.com'}))
        self.stack.enter_context(patch.object(auth, 'vault', return_value=Mock()))
        self.open = self.stack.enter_context(patch.object(auth.webbrowser, 'open', return_value=True))
        self.save = self.stack.enter_context(patch.object(auth, 'save_token'))
        self.stack.enter_context(patch('logger.log_event'))
        self.oauth = auth.DesktopOAuth()
        self.success = AsyncMock()

    async def asyncTearDown(self):
        await self.oauth.stop()
        self.stack.close()

    async def callback(self, path):
        port = self.oauth.server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        writer.write(f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'.encode())
        await writer.drain()
        response = await reader.read()
        writer.close(); await writer.wait_closed()
        return response

    async def test_state_pkce_and_cancellation(self):
        await self.oauth.start(self.success)
        params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertGreater(len(params['code_challenge'][0]), 40)
        self.assertTrue(params['redirect_uri'][0].startswith('http://127.0.0.1:'))
        result = await self.callback('/callback?state=wrong&code=fake')
        self.assertIn(b'400', result)
        self.assertFalse(self.oauth.task.done())
        await self.oauth.stop()
        self.assertEqual(self.oauth.state, 'idle')
        self.assertFalse(self.oauth.server.is_serving())
        self.save.assert_not_called()

    async def test_one_pending_flow_only(self):
        await self.oauth.start(self.success)
        with self.assertRaises(auth.HTTPException):
            await self.oauth.start(self.success)
        self.assertEqual(self.open.call_count, 1)

    async def test_success_token_only_in_vault(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=(
            {'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'scope': ' '.join(auth.SCOPES), 'expires_in': 3600}
            if request.url.path == '/token' else {'sub': 'stable-id', 'email': 'fake@example.test'})))
        real_client = httpx.AsyncClient
        with patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=transport, **kw)):
            await self.oauth.start(self.success)
            params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
            await self.callback('/callback?state=' + params['state'][0] + '&code=fake-code')
            await asyncio.wait_for(self.oauth.task, 5)
        self.assertEqual(self.oauth.state, 'connected')
        self.success.assert_awaited_once_with({'sub': 'stable-id', 'email': 'fake@example.test'})
        self.assertEqual(self.save.call_args.args[0], 'stable-id')
        self.assertIn(auth.EVENTS_SCOPE, self.save.call_args.args[1]['scope'])
        self.assertNotIn('fake-access', repr(vars(self.oauth)))

    async def test_refresh_and_revoked_token(self):
        token = {'access_token': 'old', 'refresh_token': 'refresh', 'expires_at': 0}
        real_client = httpx.AsyncClient
        for status in (200, 400):
            transport = httpx.MockTransport(lambda request: httpx.Response(status, json={'access_token': 'new', 'expires_in': 3600}))
            with patch.object(auth, 'load_token', return_value=token.copy()), patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=transport, **kw)):
                if status == 200:
                    self.assertEqual(await auth.access_token('account'), 'new')
                    self.assertEqual(self.save.call_args.args[1]['refresh_token'], 'refresh')
                else:
                    with self.assertRaises(auth.HTTPException) as error:
                        await auth.access_token('account')
                    self.assertEqual(error.exception.status_code, 401)


class PlannerEdgeTests(PlannerFixture):
    def test_deleted_parent_does_not_block_preparation(self):
        parent = self.create(kind='event', date='2030-01-01')
        child = self.create(parent_id=parent['id'])
        self.client.delete(f'/api/tasks/{parent["id"]}?revision=1')
        response = self.client.patch('/api/tasks/' + child['id'], json={'revision': 1, 'status': 'done'})
        self.assertEqual(response.status_code, 200, response.text)
        detail = self.client.get('/api/tasks/' + child['id']).json()
        self.assertIsNotNone(detail['parent']['deleted_at'])

    def test_undated_rename_keeps_reminder(self):
        item = self.create()
        self.client.post('/api/tasks/' + item['id'] + '/reminders', json={'revision': 1, 'date': '2030-01-01', 'time': '10:00'})
        response = self.client.patch('/api/tasks/' + item['id'], json={'revision': 1, 'title': 'Нова назва'})
        self.assertEqual(response.json()['reminders'][0]['state'], 'pending')

    def test_validation_remains_422(self):
        self.assertEqual(self.client.post('/api/tasks', json={}).status_code, 422)
