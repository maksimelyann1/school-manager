from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from integrations.codex_mcp.bridge import BridgeError, SchoolManager, local_time, resolve_date


class BridgeTests(unittest.TestCase):
    def test_relative_saturday_uses_local_time_and_skips_elapsed(self):
        friday = datetime(2026, 10, 23, 18, tzinfo=timezone.utc)
        self.assertEqual(resolve_date(weekday=5, now=friday)["date"], "2026-10-24")
        saturday = friday + timedelta(days=1)
        self.assertEqual(resolve_date(weekday=5, now=saturday)["date"], "2026-10-31")

    def test_dst_nonexistent_and_ambiguous_times_require_resolution(self):
        for day in ("2026-03-29", "2026-10-25"):
            with self.assertRaises(BridgeError):
                local_time(day, "03:30", "Europe/Kyiv")
        first = local_time("2026-10-25", "03:30", "Europe/Kyiv", 0)
        second = local_time("2026-10-25", "03:30", "Europe/Kyiv", 1)
        self.assertEqual(second.astimezone(timezone.utc) - first.astimezone(timezone.utc), timedelta(hours=1))

    def test_loopback_only_and_no_path_credentials(self):
        for url in ("https://example.com", "http://127.0.0.1@evil.test", "http://127.0.0.1/a", "http://user@localhost", "http://localhost?token=x"):
            with self.assertRaises(BridgeError):
                SchoolManager(url)

    def test_incompatible_server_prevents_writes(self):
        requests = []
        def handler(request):
            requests.append(request.method)
            return httpx.Response(200, json={"service": "unrelated"})
        client = SchoolManager(transport=httpx.MockTransport(handler))
        with self.assertRaises(BridgeError):
            client.request("POST", "/api/tasks", json={"title": "x"})
        self.assertEqual(requests, ["GET"])

    def test_offline_status_is_actionable(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)
        result = SchoolManager(transport=httpx.MockTransport(handler)).status()
        self.assertFalse(result["online"])
        self.assertIn("Відкрийте", result["error"])

    def test_malformed_id_never_reaches_http(self):
        client = SchoolManager()
        client.request = Mock()
        with self.assertRaises(BridgeError):
            client.get_item("../../settings")
        client.request.assert_not_called()

    def test_partial_creation_returns_existing_item_and_retry_instruction(self):
        client = SchoolManager()
        identity = uuid4().hex
        day = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        client.request = Mock(return_value={"id": identity, "revision": 1, "title": "Заняття",
            "description": "", "kind": "event", "date": day, "time": "11:00",
            "end_date": day, "end_time": "12:00", "timezone": "Europe/Kyiv"})
        client.set_reminder = Mock(side_effect=BridgeError("Тайм-аут"))
        result = client.create("Заняття", identity, "event", day, "11:00", remind_before_minutes=0)
        self.assertTrue(result["partial"])
        self.assertEqual(result["item"]["id"], identity)
        self.assertEqual(client.request.call_count, 1)

    def test_past_reminder_rejected_before_creation(self):
        client = SchoolManager()
        client.request = Mock()
        with self.assertRaises(BridgeError):
            client.create("Заняття", str(uuid4()), "event", "2020-01-01", "11:00", remind_before_minutes=0)
        client.request.assert_not_called()

    def test_all_day_event_keeps_inclusive_last_day_and_options(self):
        client = SchoolManager()
        def save(method, path, json):
            return {**json, "id": json["request_id"], "revision": 1, "status": "open"}
        client.request = Mock(side_effect=save)
        result = client.create("Канікули", str(uuid4()), "event", "2027-01-01",
            options={"category": "other", "location": "Школа", "recurrence": ["RRULE:FREQ=YEARLY;COUNT=2"]},
            end_day="2027-01-03")
        self.assertTrue(result["ok"])
        item = result["item"]
        self.assertIsNone(item["time"])
        self.assertEqual(item["end_date"], "2027-01-03")
        self.assertEqual(item["category"], "other")
        self.assertEqual(item["location"], "Школа")
        self.assertEqual(item["recurrence"], ["RRULE:FREQ=YEARLY;COUNT=2"])

    def test_invalid_all_day_span_or_timed_end_day_never_creates(self):
        client = SchoolManager()
        client.request = Mock()
        for day, clock, end_day in (("2027-01-02", None, "2027-01-01"),
                                   ("20270102", None, None),
                                   ("2027-01-01", "11:00", "2027-01-02")):
            with self.subTest(day=day, clock=clock), self.assertRaises(BridgeError):
                client.create("Подія", str(uuid4()), "event", day, clock, end_day=end_day)
        client.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
