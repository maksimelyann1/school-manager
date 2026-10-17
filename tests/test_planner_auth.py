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
        self.log = self.stack.enter_context(patch('logger.log_event'))
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

    async def test_closed_browser_is_unfinished_login_not_network_failure(self):
        with patch.object(auth, 'OAUTH_WAIT_SECONDS', .03):
            await self.oauth.start(self.success)
            await asyncio.wait_for(self.oauth.task, 2)
        self.assertEqual(self.oauth.state, 'idle')
        self.assertIsNone(self.oauth.error)
        self.assertIn('не завершено', self.oauth.notice)
        self.assertFalse(self.oauth.server.is_serving())
        self.save.assert_not_called()
        self.success.assert_not_awaited()
        self.assertEqual(self.log.call_args.args[0], 'INFO')
        await self.oauth.start(self.success)
        self.assertEqual(self.oauth.state, 'waiting')
        self.assertIsNone(self.oauth.notice)

    async def test_denied_consent_is_cancellation_and_keeps_saved_account(self):
        await self.oauth.start(self.success)
        params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
        response = await self.callback('/callback?state=' + params['state'][0] + '&error=access_denied')
        self.assertIn('не завершено'.encode(), response)
        await asyncio.wait_for(self.oauth.task, 2)
        self.assertEqual(self.oauth.state, 'idle')
        self.assertIsNone(self.oauth.error)
        self.assertIn('скасовано', self.oauth.notice)
        self.save.assert_not_called()
        self.success.assert_not_awaited()
        self.assertEqual(self.log.call_args.args[0], 'INFO')

    async def test_real_google_timeout_is_logged_as_error_without_secrets(self):
        async def failing(request):
            raise httpx.ReadTimeout('PRIVATE fake-code fake-access', request=request)
        real_client = httpx.AsyncClient
        with patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(failing), **kw)):
            await self.oauth.start(self.success)
            params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
            response = await self.callback('/callback?state=' + params['state'][0] + '&code=fake-code')
            await asyncio.wait_for(self.oauth.task, 2)
        self.assertEqual(self.oauth.state, 'error')
        self.assertIn('Не вдалося завершити вхід'.encode(), response)
        self.assertNotIn('<h1 id="result-title">Вхід завершено'.encode(), response)
        self.assertIsNone(self.oauth.notice)
        self.assertEqual(self.log.call_args.args[0], 'ERROR')
        logged = self.log.call_args.args[2]
        self.assertIn('ReadTimeout', logged)
        self.assertIn('обмін коду', logged)
        for secret in ('PRIVATE', 'fake-code', 'fake-access'):
            self.assertNotIn(secret, logged)
        self.save.assert_not_called()

    async def test_google_rejection_logs_http_status_without_response_body(self):
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(lambda request: httpx.Response(400, json={'error': 'invalid_grant', 'PRIVATE': 'fake-access'}))
        with patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=transport, **kw)):
            await self.oauth.start(self.success)
            params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
            await self.callback('/callback?state=' + params['state'][0] + '&code=fake-code')
            await asyncio.wait_for(self.oauth.task, 2)
        self.assertEqual(self.oauth.state, 'error')
        self.assertIn('HTTP 400', self.log.call_args.args[2])
        self.assertNotIn('PRIVATE', self.log.call_args.args[2])
        self.assertNotIn('fake-access', self.log.call_args.args[2])

    async def test_stop_clears_previous_error_without_touching_tokens(self):
        self.oauth.state, self.oauth.error = 'error', 'Попередня помилка'
        await self.oauth.stop()
        self.assertEqual(self.oauth.state, 'idle')
        self.assertIsNone(self.oauth.error)
        self.save.assert_not_called()

    async def test_google_callback_error_is_not_mislabelled_as_user_cancellation(self):
        await self.oauth.start(self.success)
        params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
        await self.callback('/callback?state=' + params['state'][0] + '&error=invalid_scope')
        await asyncio.wait_for(self.oauth.task, 2)
        self.assertEqual(self.oauth.state, 'error')
        self.assertIsNone(self.oauth.notice)
        self.assertEqual(self.log.call_args.args[0], 'ERROR')

    async def test_success_token_only_in_vault(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=(
            {'access_token': 'fake-access', 'refresh_token': 'fake-refresh', 'scope': ' '.join(auth.SCOPES), 'expires_in': 3600}
            if request.url.path == '/token' else {'sub': 'stable-id', 'email': 'fake@example.test'})))
        real_client = httpx.AsyncClient
        with patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=transport, **kw)):
            await self.oauth.start(self.success)
            params = parse_qs(urlsplit(self.open.call_args.args[0]).query)
            response = await self.callback('/callback?state=' + params['state'][0] + '&code=fake-code')
            await asyncio.wait_for(self.oauth.task, 5)
        self.assertEqual(self.oauth.state, 'connected')
        self.success.assert_awaited_once_with({'sub': 'stable-id', 'email': 'fake@example.test'})
        self.assertEqual(self.save.call_args.args[0], 'stable-id')
        self.assertIn(auth.EVENTS_SCOPE, self.save.call_args.args[1]['scope'])
        self.assertNotIn('fake-access', repr(vars(self.oauth)))
        headers, body = response.split(b'\r\n\r\n', 1)
        self.assertIn(b'Content-Type: text/html; charset=utf-8', headers)
        self.assertIn(b'Content-Security-Policy:', headers)
        self.assertIn('Вхід завершено'.encode(), body)
        self.assertIn('Можете закрити цю вкладку та повернутися до School Manager.'.encode(), body)
        self.assertIn(f'Content-Length: {len(body)}'.encode(), headers)
        for secret in (b'fake-access', b'fake-refresh', b'fake-code', params['state'][0].encode()):
            self.assertNotIn(secret, body)

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

    async def test_refresh_discards_id_token_and_preserves_background_authorization(self):
        old = {'access_token': 'old', 'refresh_token': 'refresh', 'expires_at': 0, 'scope': auth.EVENTS_SCOPE}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            'access_token': 'new', 'id_token': 'x' * 1800, 'token_type': 'Bearer', 'expires_in': 3600}))
        real_client = httpx.AsyncClient
        with patch.object(auth, 'load_token', return_value=old), \
             patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=transport, **kw)):
            self.assertEqual(await auth.access_token('account'), 'new')
        saved = self.save.call_args.args[1]
        self.assertNotIn('id_token', saved)
        self.assertNotIn('token_type', saved)
        self.assertEqual(saved['refresh_token'], 'refresh')
        self.assertEqual(saved['scope'], auth.EVENTS_SCOPE)

    async def test_concurrent_requests_refresh_once(self):
        store = {'access_token': 'old', 'refresh_token': 'refresh', 'expires_at': 0}
        requests = []
        async def refresh(request):
            requests.append(request)
            await asyncio.sleep(.02)
            return httpx.Response(200, json={'access_token': 'new', 'expires_in': 3600})
        real_client = httpx.AsyncClient
        with patch.object(auth, 'refresh_lock', asyncio.Lock()), \
             patch.object(auth, 'load_token', side_effect=lambda account: store.copy()), \
             patch.object(auth, 'save_token', side_effect=lambda account, value: store.update(value)), \
             patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(refresh), **kw)):
            self.assertEqual(await asyncio.gather(*(auth.access_token('account') for _ in range(3))), ['new'] * 3)
        self.assertEqual(len(requests), 1)


class TokenStorageTests(unittest.TestCase):
    def test_windows_vault_never_receives_unused_oauth_fields(self):
        storage = Mock()
        with patch.object(auth, 'vault', return_value=storage):
            auth.save_token('account', {'access_token': 'a' * 240, 'refresh_token': 'r' * 100,
                'expires_at': time.time() + 3600, 'scope': ' '.join(auth.SCOPES), 'id_token': 'x' * 1800})
        value = storage.set_password.call_args.args[2]
        self.assertLess(len(value.encode('utf-16-le')), 2560)
        self.assertNotIn('id_token', json.loads(value))

    def test_storage_failure_has_a_readable_message_and_no_secret_in_logs(self):
        storage = Mock()
        storage.set_password.side_effect = OSError('PRIVATE TOKEN')
        with patch.object(auth, 'vault', return_value=storage), patch('logger.log_event') as log:
            with self.assertRaises(auth.HTTPException) as error:
                auth.save_token('account', {'access_token': 'SECRET'})
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn('SECRET', repr(log.call_args))
        self.assertNotIn('PRIVATE', repr(log.call_args))


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
