"""Exercise real stdio MCP. --fixture also exercises the isolated backend API."""
import argparse
import asyncio
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def exercise_application(call, session, url):
    with tempfile.TemporaryDirectory(prefix="mcp-assets-", dir=ROOT / "tmp") as directory:
        folder = Path(directory)
        upload = folder / "матеріали.txt"
        upload.write_text("Матеріали для тестового уроку", encoding="utf-8")
        category = await call("create_category", {"name": "MCP тест"})
        group = await call("create_group", {"name": "Тестова група", "telegram_id": "-100000123",
                                          "category_id": category["id"], "lesson_time": "11:00", "lesson_day": "субота"})
        changed = await call("update_group", {"group_id": group["id"], "changes": {"name": "Тестова група MCP"}})
        assert changed["telegram_id"] == group["telegram_id"] and changed["category_id"] == category["id"]
        template = await call("create_template", {"name": "Нагадування", "text": "<b>Урок</b> завтра 🙂",
            "uploads": [{"path": str(upload)}], "stickers": [{"file_id": "fixture-sticker"}]})
        updated = await call("update_template", {"template_id": template["id"], "changes": {"text": "<b>Заняття</b> завтра 🙂"}})
        assert len(updated["files"]) == 1 and updated["stickers"] == template["stickers"]
        duplicate = await call("duplicate_template", {"template_id": template["id"], "name": "Копія"})
        assert len(duplicate["files"]) == 1 and duplicate["stickers"] == template["stickers"]
        downloaded = await call("download_attachment", {"storage": "template", "stored_filename": duplicate["files"][0]["stored_filename"],
                                                       "destination": str(folder / "копія.txt")})
        assert Path(downloaded["path"]).read_bytes() == upload.read_bytes()
        sent = await call("send_template", {"template_id": template["id"], "group_ids": [group["id"]]})
        assert sent["results"][0]["success"] is True
        scheduled = await call("schedule_template", {"template_id": template["id"], "group_id": group["id"],
            "send_day": "субота", "send_time": "11:00", "repeat_count": 2})
        await call("update_scheduled_message", {"message_id": scheduled["id"], "changes": {"send_time": "12:00"}})
        await call("set_scheduled_message_active", {"message_id": scheduled["id"], "active": False})
        same = await call("set_scheduled_message_active", {"message_id": scheduled["id"], "active": False})
        assert not same["changed"]
        rows = await call("list_scheduled_messages", {"group_id": group["id"]})
        assert rows["items"][0]["send_time"] == "12:00" and len(rows["items"][0]["files"]) == 1
        before = await call("get_report_settings")
        settings = await call("update_report_settings", {"changes": {"prompt_template": "Тестовий промпт MCP"}})
        assert settings["auto_reports_enabled"] == before["auto_reports_enabled"] is False
        assert settings["absent_followup_enabled"] == before["absent_followup_enabled"] is False
        assert settings["prompt_template"] == "Тестовий промпт MCP"
        course = await call("create_course", {"name": "Курс MCP"})
        topic = await call("create_course_lesson", {"course_id": course["id"], "fields": {
            "lesson_count": 1, "lesson_code": "М1У1", "lesson_title": "Тема MCP", "lesson_report_text": "Матеріал звіту"}})
        details = await call("get_course", {"course_id": course["id"]})
        assert details["lessons"][0]["id"] == topic["id"]
        lesson = await call("create_lesson", {"fields": {"group_name": "Заняття MCP", "day": "ПТ",
            "start_time": "11:00", "duration_minutes": 60, "telegram_group_id": group["id"]}})
        tomorrow = (datetime.now(ZoneInfo("Europe/Kyiv")) + timedelta(days=1)).date().isoformat()
        postponed = await call("postpone_lesson", {"lesson_id": lesson["id"], "day": tomorrow, "clock": "12:00"})
        assert postponed["is_postponed"]
        await call("cancel_lesson_postponement", {"lesson_id": lesson["id"]})
        paused = await call("set_lesson_paused", {"lesson_id": lesson["id"], "paused": True})
        assert paused["is_paused"]
        await call("set_lesson_paused", {"lesson_id": lesson["id"], "paused": False})
        # Use a pending, dated occurrence; existing send code remains unchanged.
        report_day = (datetime.now(ZoneInfo("Europe/Kyiv")) - timedelta(days=1)).date()
        weekday = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "НД"][report_day.weekday()]
        await call("update_lesson", {"lesson_id": lesson["id"], "changes": {"day": weekday, "start_time": "00:00"}})
        context = await call("prepare_report_context", {"lesson_id": lesson["id"], "lesson_date": report_day.isoformat()})
        assert "absents" in context and "message" not in context
        report = await call("send_report", {"lesson_id": lesson["id"], "lesson_date": report_day.isoformat(), "test": False})
        assert report["ok"]
        runs = await call("list_report_runs", {"group": "Заняття MCP"})
        assert runs["items"][0]["status"] == "success"
        double = await session.call_tool("send_report", {"lesson_id": lesson["id"], "lesson_date": report_day.isoformat(), "test": False})
        assert double.isError, "Existing duplicate-report guard must reject a second send"
        runs_after = await call("list_report_runs", {"group": "Заняття MCP"})
        assert len(runs_after["items"]) == 1
        export = await call("export_report_workbook", {"destination": str(folder / "розклад.xlsx")})
        assert Path(export["path"]).read_bytes().startswith(b"PK")
        task = await call("create_task", {"title": "Завдання з файлом", "request_id": str(uuid4())})
        attachment = await call("task_attachment", {"item_id": task["item"]["id"], "action": "add", "upload_path": str(upload)})
        file = await call("task_attachment", {"item_id": task["item"]["id"], "action": "download",
            "attachment_id": attachment["id"], "destination": str(folder / "задача.txt")})
        assert Path(file["path"]).read_bytes() == upload.read_bytes()
        await call("task_attachment", {"item_id": task["item"]["id"], "action": "delete", "attachment_id": attachment["id"]})
        deleted = await call("delete_item", {"item_id": task["item"]["id"], "revision": task["item"]["revision"]})
        restored = await call("restore_item", {"item_id": deleted["id"], "revision": deleted["revision"]})
        assert restored["deleted_at"] is None
        await call("delete_scheduled_message", {"message_id": scheduled["id"]})
        await call("delete_template", {"template_id": duplicate["id"]})
        with httpx.Client(trust_env=False) as client:
            evidence = client.get(url + "/__test__/evidence").json()
        assert evidence["simulated_message_sends"] == 1 and evidence["simulated_report_sends"] == 1
        assert evidence["simulated_ai_calls"] == 1 and not evidence["scheduler_running"]
        return evidence


async def exercise(fixture=False, url=None):
    env = {**os.environ, "PYTHONUTF8": "1"}
    if url:
        env["SCHOOL_MANAGER_URL"] = url
    parameters = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("server.py"))], env=env)
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            identity = await session.initialize()
            tools = await session.list_tools()
            assert {"get_status", "create_event", "update_template", "send_report", "check_reports",
                    "create_scheduled_message", "get_course", "google_calendar", "logika"} <= {t.name for t in tools.tools}

            async def call(name, arguments=None):
                result = await session.call_tool(name, arguments or {})
                assert not result.isError, (name, result.content)
                assert isinstance(result.structuredContent, dict), (name, result)
                return result.structuredContent

            status = await call("get_status")
            if not fixture:
                print(json.dumps({"server": identity.serverInfo.name, "tools": len(tools.tools), "status": status}, ensure_ascii=False))
                return
            assert status["online"] and status["health"]["fixture"]
            tomorrow = await call("resolve_local_date", {"days_ahead": 1, "clock": "11:00"})
            request_id = str(uuid4())
            args = {"title": "Годинне заняття з Максимом", "request_id": request_id,
                    "day": tomorrow["date"], "clock": "11:00", "duration_minutes": 60, "remind_before_minutes": 0}
            first = await call("create_event", args)
            assert first["ok"]
            second = await call("create_event", args)
            assert second["ok"] and second["item"]["id"] == first["item"]["id"]
            saved = await call("get_item", {"item_id": first["item"]["id"]})
            assert len(saved["reminders"]) == 1
            assert saved["reminders"][0]["channel"] == "system"
            assert saved["time"] == "11:00" and saved["end_time"] == "12:00"
            moved = await call("update_item", {"item_id": saved["id"], "revision": saved["revision"],
                "changes": {"time": "12:00", "end_time": "13:00"}})
            assert moved["time"] == "12:00" and moved["end_time"] == "13:00"
            assert moved["reminders"][0]["remind_at"] != saved["reminders"][0]["remind_at"]
            stale = await session.call_tool("update_item", {"item_id": saved["id"], "revision": saved["revision"],
                "changes": {"title": "Стара правка"}})
            assert stale.isError
            items = await call("list_items", {"start": tomorrow["date"],
                "end": (datetime.fromisoformat(tomorrow["date"]) + timedelta(days=1)).date().isoformat()})
            assert items["total"] == 1
            task = await call("create_task", {"title": "Підготувати матеріали", "request_id": str(uuid4())})
            assert task["ok"]
            report_day = (datetime.now(ZoneInfo("Europe/Kyiv")) - timedelta(days=1)).date().isoformat()
            reports = await call("check_reports", {"start": report_day, "end": report_day})
            assert reports["all_sent"] is False
            assert reports["counts"] == {"sent": 1, "missing": 1, "error": 1, "unconfirmed": 1, "manual_required": 1}, reports
            assert (await call("check_reports", {"start": report_day, "end": report_day, "group": "Доставлено"}))["all_sent"] is True
            assert (await call("list_lessons"))["items"]
            assert (await call("list_groups"))["items"] == []
            evidence = await exercise_application(call, session, url)
            print(json.dumps({"server": identity.serverInfo.name, "tools": len(tools.tools),
                "fixture": "passed", "event_duration_minutes": 60, "duplicate_events": 0,
                "reminders": 1, "revision_conflict": "rejected", "report_counts": reports["counts"],
                "expanded_api_scenarios": "passed", **evidence}, ensure_ascii=False))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true")
    options = parser.parse_args()
    if not options.fixture:
        asyncio.run(exercise())
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    (ROOT / "tmp").mkdir(exist_ok=True)
    log = ROOT / "tmp" / "mcp-fixture.log"
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen([str(ROOT / "backend/venv/Scripts/python.exe"), str(ROOT / "tests/assistant_preview.py"), "--port", str(port)],
            cwd=ROOT, stdout=stream, stderr=stream, env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 45
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Fixture stopped; see " + str(log))
                    try:
                        if client.get(url + "/api/assistant/status").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Fixture startup timed out; see " + str(log))
            asyncio.run(exercise(True, url))
        finally:
            if process.poll() is None:
                try:
                    with httpx.Client(trust_env=False, timeout=2) as client:
                        client.post(url + "/__test__/shutdown")
                    process.wait(timeout=10)
                except (httpx.RequestError, subprocess.TimeoutExpired):
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            check=False, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
