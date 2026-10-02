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

SCOPES = ['openid', 'email', 'https://www.googleapis.com/auth/calendar.app.created',
          'https://www.googleapis.com/auth/calendar.calendarlist.readonly',
          'https://www.googleapis.com/auth/calendar.events']
EVENTS_SCOPE = 'https://www.googleapis.com/auth/calendar.events'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SERVICE = 'SchoolManager.Planner.Google'


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
    vault().set_password(SERVICE, account, json.dumps(value))


def delete_token(account):
    if vault().get_password(SERVICE, account):
        vault().delete_password(SERVICE, account)


async def access_token(account):
    token = await asyncio.to_thread(load_token, account)
    if not token:
        raise HTTPException(401, 'Підключіть Google повторно')
    if token.get('expires_at', 0) > time.time() + 90:
        return token['access_token']
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data={**client_config(), 'grant_type': 'refresh_token', 'refresh_token': token.get('refresh_token', '')})
    if response.status_code in {400, 401}:
        raise HTTPException(401, 'Доступ Google завершився або відкликаний. Підключіть акаунт повторно')
    response.raise_for_status()
    value = response.json()
    token.update(value, expires_at=time.time() + value.get('expires_in', 3600))
    await asyncio.to_thread(save_token, account, token)
    return token['access_token']


class DesktopOAuth:
    def __init__(self):
        self.task = None
        self.state = 'idle'
        self.error = None
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
                        result.set_exception(HTTPException(400, 'Вхід у Google скасовано'))
                body = ('Вхід завершено. Поверніться до School Manager.' if valid else 'Некоректний запит.').encode('utf-8')
                writer.write(f'HTTP/1.1 {200 if valid else 400} OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'.encode() + body)
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
        self.state, self.error = 'waiting', None

        async def finish():
            try:
                code = await asyncio.wait_for(result, timeout=180)
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(TOKEN_URL, data={**config, 'code': code, 'code_verifier': verifier,
                        'redirect_uri': redirect, 'grant_type': 'authorization_code'})
                    response.raise_for_status()
                    token = response.json()
                    if not set(SCOPES[2:]).issubset(set(token.get('scope', '').split())):
                        raise HTTPException(403, 'Надайте дозволи календаря для синхронізації')
                    profile = await client.get('https://openidconnect.googleapis.com/v1/userinfo', headers={'Authorization': f'Bearer {token["access_token"]}'})
                    profile.raise_for_status()
                    person = profile.json()
                if not token.get('refresh_token'):
                    raise HTTPException(401, 'Не отримано дозвіл на фонову синхронізацію. Повторіть вхід')
                token = {key: token[key] for key in ('access_token', 'refresh_token', 'expires_in', 'scope') if key in token}
                token['expires_at'] = time.time() + token.get('expires_in', 3600)
                await asyncio.to_thread(save_token, person['sub'], token)
                await on_success(person)
                self.state = 'connected'
            except asyncio.CancelledError:
                self.state = 'idle'
                raise
            except Exception as error:
                from logger import log_event
                self.state = 'error'
                self.error = error.detail if isinstance(error, HTTPException) else 'Не вдалося підключити Google. Перевірте мережу й повторіть вхід'
                log_event('ERROR', 'Planner', self.error)
            finally:
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


oauth = DesktopOAuth()
