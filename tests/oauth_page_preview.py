"""Real loopback OAuth callback UI with fake Google and secure-storage substitutes."""
import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
from services.planner import google_auth as auth


async def main():
    oauth = auth.DesktopOAuth()
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=(
        {'access_token': 'fake', 'refresh_token': 'fake', 'scope': ' '.join(auth.SCOPES)}
        if request.url.path == '/token' else {'sub': 'fake', 'email': 'preview@example.test'})))
    with patch.object(auth, 'client_config', return_value={'client_id': 'fake.apps.googleusercontent.com'}), \
         patch.object(auth, 'vault', return_value=Mock()), patch.object(auth, 'save_token'), \
         patch.object(auth.webbrowser, 'open', return_value=True) as opened, \
         patch.object(auth.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=transport, **kw)):
        await oauth.start(AsyncMock())
        params = parse_qs(urlsplit(opened.call_args.args[0]).query)
        print(params['redirect_uri'][0] + '?state=' + params['state'][0] + '&code=fake', flush=True)
        try:
            await asyncio.Event().wait()
        finally:
            await oauth.stop()


if __name__ == '__main__':
    asyncio.run(main())
