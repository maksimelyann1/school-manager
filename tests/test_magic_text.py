import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from routers import ai


class MagicTextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = Mock()
        self.db.query.return_value.first.return_value = SimpleNamespace(
            google_ai_api_key="test-key", google_ai_model="gemini-3.8-flash")
        self.client = AsyncMock()
        self.client.__aenter__.return_value = self.client
        factory = patch.object(ai.httpx, "AsyncClient", return_value=self.client)
        factory.start()
        self.addCleanup(factory.stop)
        sleep = patch.object(ai.asyncio, "sleep", new_callable=AsyncMock)
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        log = patch.object(ai, "log_event")
        self.log = log.start()
        self.addCleanup(log.stop)

    async def invoke(self):
        return await ai.polish_text(ai.PolishTextRequest(text="Початковий текст", context="template"), self.db)

    async def test_recovers_after_two_overloaded_responses(self):
        self.client.post.side_effect = [httpx.Response(503), httpx.Response(503),
            httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Готовий текст"}]}}]})]
        self.assertEqual(await self.invoke(), {"text": "Готовий текст"})
        self.assertEqual(self.client.post.await_count, 3)
        self.assertEqual(self.sleep.await_count, 2)
        calls = self.client.post.await_args_list
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[1], calls[2])
        self.assertIn("gemini-3.8-flash:generateContent", calls[0].args[0])
        self.assertNotIn("test-key", str(self.log.call_args_list))
        self.assertNotIn("Початковий текст", str(self.log.call_args_list))

    async def test_persistent_overload_returns_friendly_error_and_stops(self):
        self.client.post.return_value = httpx.Response(503, json={"error": {"message": "high demand"}})
        with self.assertRaises(HTTPException) as caught:
            await self.invoke()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("gemini-3.8-flash", caught.exception.detail)
        self.assertIn("тимчасово не може обробити запит", caught.exception.detail)
        self.assertNotIn('"error"', caught.exception.detail)
        self.assertEqual(self.client.post.await_count, 3)

    async def test_other_errors_are_not_retried(self):
        for status in (400, 401, 403, 404, 429):
            with self.subTest(status=status):
                self.client.post.reset_mock()
                self.client.post.return_value = httpx.Response(status, text="Rejected")
                with self.assertRaises(HTTPException):
                    await self.invoke()
                self.assertEqual(self.client.post.await_count, 1)
        self.sleep.assert_not_awaited()

    async def test_success_does_not_retry(self):
        self.client.post.return_value = httpx.Response(200,
            json={"candidates": [{"content": {"parts": [{"text": "Готово"}]}}]})
        self.assertEqual(await self.invoke(), {"text": "Готово"})
        self.client.post.assert_awaited_once()
        self.sleep.assert_not_awaited()

    async def test_timeout_is_friendly_and_not_retried(self):
        self.client.post.side_effect = httpx.ReadTimeout("Timed out")
        with self.assertRaises(HTTPException) as caught:
            await self.invoke()
        self.assertEqual(caught.exception.status_code, 504)
        self.assertIn("не відповів вчасно", caught.exception.detail)
        self.client.post.assert_awaited_once()

    async def test_total_timeout_cancels_inflight_request(self):
        real_wait = asyncio.wait_for
        async def short_wait(work, timeout):
            self.assertEqual(timeout, 60.0)
            return await real_wait(work, timeout=0.01)
        cancelled = asyncio.Event()
        async def hanging(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.client.post.side_effect = hanging
        with patch.object(ai.asyncio, "wait_for", side_effect=short_wait):
            with self.assertRaises(HTTPException) as caught:
                await self.invoke()
        self.assertEqual(caught.exception.status_code, 504)
        self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
