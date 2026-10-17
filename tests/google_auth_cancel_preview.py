"""Cancelled OAuth UI and calendar-link recovery without real services."""
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import calendar_sync_preview as preview
from services.planner.items import utc_now


class FakeGoogle(preview.FakeGoogle):
    async def pages(self, path, params=None):
        values, token = await super().pages(path, params)
        if path == '/users/me/calendarList':
            for value in values:
                if value['id'] == 'app':
                    value['description'] = preview.planner_google.calendar_marker('fake-account')
        return values, token


@asynccontextmanager
async def lifespan(app):
    async with preview.lifespan(app):
        with ExitStack() as stack:
            stack.enter_context(patch.object(preview.planner_google, 'oauth', SimpleNamespace(
                state='idle', error=None, stage=None,
                notice='Вхід у Google не завершено в браузері. Можна повторити підключення',
                start=AsyncMock(), stop=AsyncMock())))
            for module in (preview.google, preview.planner_google):
                stack.enter_context(patch.object(module, 'GoogleAPI', side_effect=lambda *args: FakeGoogle()))
            yield


app = preview.app
app.router.lifespan_context = lifespan
with preview.sessions() as db:
    connection = db.get(preview.PlannerConnection, 'preview')
    connection.state, connection.last_error, connection.sync_attempts = 'connected', None, 0
    connection.last_sync_at = utc_now()
    calendar = db.get(preview.PlannerCalendar, 1)
    calendar.managed, calendar.visible = 0, 0
    db.commit()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8768)
