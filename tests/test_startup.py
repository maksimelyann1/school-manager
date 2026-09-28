import asyncio
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main
from models import Base, LogikaSettings
from startup_state import startup_state


class StartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.stack = ExitStack()
        for target, value in [
            ("engine", self.engine), ("SessionLocal", self.sessions),
            ("ensure_schema_migrations", Mock()),
            ("pyrogram_manager", SimpleNamespace(is_connected=False, disconnect=AsyncMock())),
        ]:
            self.stack.enter_context(patch.object(main, target, value))
        for target in ["services.planner.schema.ensure_planner_migrations",
                       "services.planner.reminders.init_scheduler",
                       "main.parents_report.init_scheduler", "main.auto_messages.init_scheduler",
                       "main.auto_messages.scheduler.start", "main.auto_messages.scheduler.shutdown",
                       "main.stickers.cancel_sticker_cache_warmup", "logger.log_event"]:
            self.stack.enter_context(patch(target))
        self.stack.enter_context(patch.object(main.planner_google.oauth, "stop", AsyncMock()))
        startup_state.reset()

    def tearDown(self):
        self.stack.close()
        self.engine.dispose()
        self.tmp.cleanup()
        startup_state.reset()

    async def test_http_and_settings_respond_while_both_services_are_waiting(self):
        entered = {name: asyncio.Event() for name in ("telegram", "logika")}
        release = asyncio.Event()
        async def slow(name):
            startup_state.set(name, "running", f"Connecting {name}")
            entered[name].set()
            await release.wait()
            startup_state.set(name, "done", f"Connected {name}")
        with patch.object(main, "_startup_telegram", lambda: slow("telegram")), \
             patch.object(main, "_startup_logika", lambda: slow("logika")):
            async with main.lifespan(main.app):
                await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), 1)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                    for path in ("/health", "/api/startup", "/"):
                        response = await asyncio.wait_for(client.get(path), 0.5)
                        self.assertEqual(response.status_code, 200)
                    status = (await client.get("/api/startup")).json()
                    self.assertTrue(status["ready"])
                    self.assertFalse(status["finished"])
                db = self.sessions()
                try:
                    with patch.object(main.settings, "pyrogram_manager", SimpleNamespace(is_connected=False)), \
                         patch.object(main.settings, "_safe_settings_response", return_value={"has_session": True}):
                        result = await asyncio.wait_for(main.settings.get_bot_settings(db), 0.5)
                        self.assertTrue(result["has_session"])
                finally:
                    db.close()
                release.set()
                await asyncio.gather(*main.app.state.startup_tasks)
                self.assertTrue(startup_state.snapshot()["finished"])

    async def test_shutdown_cancels_services_before_disconnecting_and_closing_database(self):
        cancelled = []
        async def pending(name):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(name)
        async def disconnect():
            self.assertEqual(set(cancelled), {"telegram", "logika"})
        main.pyrogram_manager.disconnect.side_effect = disconnect
        with patch.object(main, "_startup_telegram", lambda: pending("telegram")), \
             patch.object(main, "_startup_logika", lambda: pending("logika")):
            async with main.lifespan(main.app):
                await asyncio.sleep(0.01)
            self.assertTrue(all(task.done() for task in main.app.state.startup_tasks))
            main.pyrogram_manager.disconnect.assert_awaited_once()

    async def test_offline_and_timeout_finish_with_visible_error(self):
        for timeout, error in [(1, OSError("network offline")), (0.01, None)]:
            async def fail():
                if error:
                    raise error
                await asyncio.Event().wait()
            await main._run_startup_service("logika", fail, timeout)
            step = startup_state.snapshot()["steps"]["logika"]
            self.assertEqual(step["state"], "error")
            self.assertIn("Збережені дані", step["message"])

    async def test_logika_not_configured_or_disabled_does_not_connect(self):
        with patch.object(main.logika, "sync_schedule", AsyncMock()) as sync:
            await main._startup_logika()
            db = self.sessions()
            db.add(LogikaSettings(login="fake", password="fake", auto_sync_enabled=0))
            db.commit()
            db.close()
            await main._startup_logika()
            sync.assert_not_awaited()
            self.assertEqual(startup_state.snapshot()["steps"]["logika"]["state"], "skipped")

    async def test_telegram_restores_scheduling_before_optional_group_sync(self):
        client = SimpleNamespace(has_session=lambda: True, connect_with_session=AsyncMock(return_value=True))
        order = []
        async def scheduling():
            order.append("messages")
        async def groups(_db):
            order.append("groups")
            raise OSError("group list unavailable")
        with patch.object(main, "pyrogram_manager", client), \
             patch.object(main, "get_effective_credentials", return_value=SimpleNamespace(api_id=1, api_hash="test")), \
             patch.object(main.auto_messages, "schedule_telegram_messages", scheduling), \
             patch.object(main.groups, "sync_telegram_groups", groups), \
             patch.object(main.stickers, "schedule_sticker_cache_warmup"):
            await main._run_startup_service("telegram", main._startup_telegram, 1)
        self.assertEqual(order, ["messages", "groups"])
        self.assertEqual(startup_state.snapshot()["steps"]["telegram"]["state"], "error")


class LauncherProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import desktop_app
        cls.launcher = desktop_app

    def test_status_does_not_wait_for_unloaded_webview(self):
        window = Mock()
        window.events.loaded.is_set.return_value = False
        with patch.object(self.launcher, "_loading_target", return_value=window):
            self.assertFalse(self.launcher._set_loading_status("Перевіряємо базу…"))
        window.evaluate_js.assert_not_called()

    def test_splash_stays_until_http_interface_has_loaded(self):
        window, splash = Mock(), Mock()
        window.get_current_url.return_value = "about:blank"
        with patch.object(self.launcher, "_window", window), \
             patch.object(self.launcher, "_splash_window", splash), \
             patch.object(self.launcher, "log_launcher"):
            self.launcher._on_interface_loaded()
            splash.destroy.assert_not_called()
            window.get_current_url.return_value = "http://127.0.0.1:8001/"
            self.launcher._on_interface_loaded()
            splash.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
