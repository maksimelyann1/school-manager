"""Desktop OAuth: system browser + short-lived loopback callback, OS credential vault."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

import httpx
from fastapi import HTTPException

from database import db_dir
from services.planner.google_errors import safe_google_error
from services.planner.oauth_page import oauth_result_page

SCOPES = ['openid', 'email', 'https://www.googleapis.com/auth/calendar.app.created',
          'https://www.googleapis.com/auth/calendar.calendarlist.readonly',
          'https://www.googleapis.com/auth/calendar.events']
EVENTS_SCOPE = 'https://www.googleapis.com/auth/calendar.events'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SERVICE = 'SchoolManager.Planner.Google'
TOKEN_FIELDS = ('access_token', 'refresh_token', 'expires_at', 'expires_in', 'scope')
refresh_lock = asyncio.Lock()
OAUTH_WAIT_SECONDS = 180


def config_path():
    return Path(os.environ.get('SCHOOL_MANAGER_GOOGLE_CLIENT', str(Path(db_dir) / 'google-desktop-client.json')))


def client_config():
    try:
        value = json.loads(config_path().read_text(encoding='utf-8'))['installed']
        if not value.get('client_id', '').endswith('.apps.googleusercontent.com'):
            raise ValueError()
        return {key: value[key] for key in ('client_id', 'client_secret') if value.get(key)}
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Налаштуйте Google OAuth Desktop: додайте google-desktop-client.json за інструкцією')


def vault():
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    if sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
        return Keyring()
    raise RuntimeError('Для Google потрібне захищене сховище Windows або macOS')


def load_token(account):
    text = vault().get_password(SERVICE, account)
    return json.loads(text) if text else None


def save_token(account, value):
    # Refresh responses also contain a large ID token, which Calendar never uses.
    value = {key: value[key] for key in TOKEN_FIELDS if key in value}
    try:
        vault().set_password(SERVICE, account, json.dumps(value, separators=(',', ':')))
    except Exception as error:
        from logger import log_event
        code = getattr(error, 'winerror', None)
        log_event('ERROR', 'Planner', f'Не вдалося зберегти доступ Google: {type(error).__name__}, код {code or "невідомий"}')
        raise HTTPException(503, 'Не вдалося зберегти доступ Google у захищеному сховищі. Повторіть підключення') from error


def delete_token(account):
    if vault().get_password(SERVICE, account):
        vault().delete_password(SERVICE, account)


async def access_token(account):
    token = await asyncio.to_thread(load_token, account)
    if not token:
        raise HTTPException(401, 'Підключіть Google повторно')
    if token.get('expires_at', 0) > time.time() + 90:
        return token['access_token']
    async with refresh_lock:
        token = await asyncio.to_thread(load_token, account)
        if not token or not token.get('refresh_token'):
            raise HTTPException(401, 'Підключіть Google повторно')
        if token.get('expires_at', 0) > time.time() + 90:
            return token['access_token']
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TOKEN_URL, data={**client_config(), 'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']})
        if response.status_code in {400, 401}:
            raise HTTPException(401, 'Доступ Google завершився або відкликаний. Підключіть акаунт повторно')
        response.raise_for_status()
        value = response.json()
        token = {key: val for key, val in {**token, **value}.items() if key in TOKEN_FIELDS}
        token['expires_at'] = time.time() + value.get('expires_in', 3600)
        await asyncio.to_thread(save_token, account, token)
        return token['access_token']


class DesktopOAuth:
    def __init__(self):
        self.task = None
        self.state = 'idle'
        self.error = None
        self.notice = None
        self.stage = None
        self.server = None
        self.start_lock = asyncio.Lock()

    async def start(self, on_success):
        async with self.start_lock:
            return await self._start(on_success)

    async def _start(self, on_success):
        if self.task and not self.task.done():
            raise HTTPException(409, 'Вхід у Google вже відкритий у браузері')
        config = client_config()
        await asyncio.to_thread(vault)  # Fail before asking for consent if secure storage is unavailable.
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        completed = loop.create_future()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')

        async def callback(reader, writer):
            try:
                line = (await asyncio.wait_for(reader.readline(), 5)).decode('ascii', errors='replace')
                parts = line.split(' ')
                parsed = urlsplit(parts[1]) if len(parts) == 3 else None
                params = parse_qs(parsed.query) if parsed else {}
                valid = bool(parts[0] == 'GET' and parsed and parsed.path == '/callback' and secrets.compare_digest(params.get('state', [''])[0], state) and not result.done())
                if valid and not result.done():
                    if params.get('code'):
                        result.set_result(params['code'][0])
                    else:
                        cancelled = params.get('error', [''])[0] == 'access_denied'
                        result.set_exception(HTTPException(400, 'Вхід у Google скасовано' if cancelled
                                                          else 'Google не повернув код входу. Повторіть підключення'))
                page_state = 'invalid'
                if valid:
                    try:
                        await asyncio.wait_for(asyncio.shield(completed), 60)
                        page_state = 'connected' if self.state == 'connected' else 'error' if self.state == 'error' else 'cancelled'
                    except asyncio.TimeoutError:
                        page_state = 'pending'
                body = oauth_result_page(page_state)
                writer.write(f'HTTP/1.1 {200 if valid else 400} OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'; frame-ancestors \'none\'\r\nConnection: close\r\n\r\n'.encode() + body)
                await writer.drain()
            except (asyncio.TimeoutError, ConnectionError, ValueError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass

        self.server = await asyncio.start_server(callback, '127.0.0.1', 0, limit=16384)
        redirect = f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/callback'
        url = AUTH_URL + '?' + urlencode({**{'client_id': config['client_id']}, 'redirect_uri': redirect,
            'response_type': 'code', 'scope': ' '.join(SCOPES), 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent select_account'})
        self.state, self.error, self.notice = 'waiting', None, None
        self.stage = 'очікування підтвердження в браузері'

        async def finish():
            try:
                try:
                    code = await asyncio.wait_for(result, timeout=OAUTH_WAIT_SECONDS)
                except asyncio.TimeoutError:
                    from logger import log_event
                    self.state, self.error = 'idle', None
                    self.notice = 'Вхід у Google не завершено в браузері. Можна повторити підключення'
                    log_event('INFO', 'Planner', 'Вхід у Google не завершено за 3 хвилини. Збережений доступ не змінено')
                    return
                self.stage = 'обмін коду входу Google'
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(TOKEN_URL, data={**config, 'code': code, 'code_verifier': verifier,
                        'redirect_uri': redirect, 'grant_type': 'authorization_code'})
                    response.raise_for_status()
                    token = response.json()
                    if not set(SCOPES[2:]).issubset(set(token.get('scope', '').split())):
                        raise HTTPException(403, 'Надайте дозволи календаря для синхронізації')
                    self.stage = 'перевірка Google-акаунта'
                    profile = await client.get('https://openidconnect.googleapis.com/v1/userinfo', headers={'Authorization': f'Bearer {token["access_token"]}'})
                    profile.raise_for_status()
                    person = profile.json()
                if not token.get('refresh_token'):
                    raise HTTPException(401, 'Не отримано дозвіл на фонову синхронізацію. Повторіть вхід')
                token = {key: token[key] for key in ('access_token', 'refresh_token', 'expires_in', 'scope') if key in token}
                token['expires_at'] = time.time() + token.get('expires_in', 3600)
                self.stage = 'збереження доступу Google'
                await asyncio.to_thread(save_token, person['sub'], token)
                self.stage = 'підключення акаунта в застосунку'
                await on_success(person)
                self.state, self.error, self.notice = 'connected', None, None
                self.stage = None
            except asyncio.CancelledError:
                self.state, self.error, self.notice = 'idle', None, None
                raise
            except Exception as error:
                from logger import log_event
                if isinstance(error, HTTPException) and error.status_code == 400 and error.detail == 'Вхід у Google скасовано':
                    self.state, self.error = 'idle', None
                    self.notice = 'Вхід у Google скасовано'
                    log_event('INFO', 'Planner', 'Вхід у Google скасовано. Збережений доступ не змінено')
                else:
                    self.state = 'error'
                    self.error = error.detail if isinstance(error, HTTPException) else 'Не вдалося підключити Google. Повторіть вхід'
                    log_event('ERROR', 'Planner', f'{self.error}. Етап: {self.stage}; {safe_google_error(error)}')
            finally:
                if not completed.done():
                    completed.set_result(None)
                self.server.close()
                await self.server.wait_closed()

        self.task = asyncio.create_task(finish())
        if not await asyncio.to_thread(webbrowser.open, url):
            await self.stop()
            raise HTTPException(503, 'Не вдалося відкрити системний браузер')
        return {'state': self.state}

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.state, self.error, self.notice, self.stage = 'idle', None, None, None


oauth = DesktopOAuth()
