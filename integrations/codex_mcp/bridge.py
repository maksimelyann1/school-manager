"""Loopback-only client. Does not import the app, open SQLite, or start its scheduler."""
from datetime import date, datetime, time, timedelta, timezone
from contextlib import ExitStack
import json
import mimetypes
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

DEFAULT_TIMEZONE = "Europe/Kyiv"


class BridgeError(RuntimeError):
    pass


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise BridgeError("Невідомий часовий пояс") from None


def local_time(day: str, clock: str, timezone_name: str, fold: int | None = None) -> datetime:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not re.fullmatch(r"\d{2}:\d{2}", clock):
            raise ValueError()
        naive = datetime.combine(date.fromisoformat(day), time.fromisoformat(clock))
    except (ValueError, TypeError):
        raise BridgeError("Вкажіть дату YYYY-MM-DD і час HH:MM") from None
    tz = zone(timezone_name)
    options = []
    for choice in (0, 1):
        value = naive.replace(tzinfo=tz, fold=choice)
        utc = value.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == naive and all(utc != old.astimezone(timezone.utc) for old in options):
            options.append(value)
    if not options:
        raise BridgeError("Цього часу не існує через переведення годинника")
    if fold not in (None, 0, 1):
        raise BridgeError("fold має бути 0 або 1")
    if len(options) > 1 and fold is None:
        raise BridgeError("Час повторюється через переведення годинника; уточніть перше або друге входження (fold)")
    return options[min(fold or 0, len(options) - 1)]


def item_id(value: str) -> str:
    try:
        return UUID(value).hex
    except (ValueError, TypeError, AttributeError):
        raise BridgeError("Потрібен UUID задачі або події з get_item/list_items") from None


def resolve_date(day: str | None = None, weekday: int | None = None, days_ahead: int | None = None,
                 clock: str = "11:00", timezone_name: str = DEFAULT_TIMEZONE,
                 fold: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    tz = zone(timezone_name)
    now = (now or datetime.now(tz)).astimezone(tz)
    if sum(value is not None for value in (day, weekday, days_ahead)) != 1:
        raise BridgeError("Вкажіть рівно одне: day, weekday (0=понеділок, 5=субота), days_ahead")
    if weekday is not None:
        if not 0 <= weekday <= 6:
            raise BridgeError("weekday має бути від 0 до 6")
        target_day = now.date() + timedelta(days=(weekday - now.weekday()) % 7)
        target = local_time(target_day.isoformat(), clock, timezone_name, fold)
        if target.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
            target_day += timedelta(days=7)
    elif days_ahead is not None:
        if not 0 <= days_ahead <= 366:
            raise BridgeError("days_ahead має бути від 0 до 366")
        target_day = now.date() + timedelta(days=days_ahead)
    else:
        try:
            target_day = date.fromisoformat(day)
        except (ValueError, TypeError):
            raise BridgeError("Вкажіть дату YYYY-MM-DD") from None
    target = local_time(target_day.isoformat(), clock, timezone_name, fold)
    return {"now": now.isoformat(), "date": target_day.isoformat(), "time": clock,
            "timezone": timezone_name, "fold": target.fold, "starts_at": target.isoformat(),
            "is_future": target.astimezone(timezone.utc) > now.astimezone(timezone.utc),
            "weekday": target.weekday()}


class SchoolManager:
    def __init__(self, base_url: str | None = None, transport=None):
        self.base_url = (base_url or os.environ.get("SCHOOL_MANAGER_URL", "http://127.0.0.1:8001")).rstrip("/")
        parsed = urlsplit(self.base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise BridgeError("SCHOOL_MANAGER_URL має бути локальною HTTP-адресою без шляху, пароля чи параметрів")
        self.transport = transport

    def exchange(self, method: str, path: str, timeout: float = 30, **kwargs):
        try:
            with httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False,
                              follow_redirects=False, transport=self.transport) as client:
                identity_response = client.get("/api/assistant/status")
                identity = self._decode(identity_response)
                if not isinstance(identity, dict) or identity.get("service") != "school_manager" or identity.get("assistant_api") != 1:
                    raise BridgeError("На цій адресі немає сумісного School Manager. Запустіть оновлену програму")
                if path == "/api/assistant/status":
                    return identity_response
                response = client.request(method, path, **kwargs)
                if response.is_error or response.is_redirect:
                    self._decode(response)
                return response
        except httpx.TimeoutException:
            raise BridgeError("School Manager не відповів вчасно. Результат операції невідомий. Перевірте стан; не повторюйте відправку або створення автоматично. Повтор із тим самим request_id дозволений лише для операцій, що його підтримують") from None
        except httpx.RequestError:
            raise BridgeError("School Manager недоступний. Відкрийте програму й повторіть запит; очікується " + self.base_url) from None

    def request(self, method: str, path: str, **kwargs):
        return self._decode(self.exchange(method, path, **kwargs))

    def upload(self, method: str, path: str, fields: dict, uploads=(), file_field="files", **kwargs):
        with ExitStack() as stack:
            files = []
            for upload in uploads:
                local = Path(upload.path).expanduser()
                if not local.is_absolute() or not local.is_file():
                    raise BridgeError("Вкажіть абсолютний шлях до наявного файла")
                filename = upload.filename or local.name
                if Path(filename).name != filename or any(c in filename for c in "\\/\r\n"):
                    raise BridgeError("Некоректна назва вкладення")
                if local.stat().st_size > 256 * 1024 * 1024:
                    raise BridgeError("Розмір вкладення перевищує 256 MB")
                files.append((file_field, (filename, stack.enter_context(local.open("rb")),
                    mimetypes.guess_type(filename)[0] or "application/octet-stream")))
            data = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else str(v)
                    for k, v in fields.items() if v is not None}
            # Multipart is needed even when only existing attachments are being changed.
            multipart = [(k, (None, v)) for k, v in data.items()] + files
            return self.request(method, path, files=multipart, **kwargs)

    def download(self, path: str, destination: str | None = None, filename="download.bin", **kwargs):
        response = self.exchange("GET", path, **kwargs)
        if response.headers.get("content-type", "").split(";")[0] == "application/json":
            body = self._decode(response)
            raise BridgeError("Файл не отримано: " + str(body.get("error", body.get("detail", "відповідь JSON"))))
        target = Path(destination).expanduser() if destination else (
            Path(__file__).resolve().parents[2] / "output/mcp" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + Path(filename).name))
        if not target.is_absolute():
            raise BridgeError("Для збереження потрібен абсолютний шлях")
        if len(response.content) > 256 * 1024 * 1024:
            raise BridgeError("Файл перевищує 256 MB")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(response.content)
        except FileExistsError:
            raise BridgeError("Файл призначення вже існує. Вкажіть новий шлях") from None
        return {"path": str(target), "size": len(response.content),
                "content_type": response.headers.get("content-type", "application/octet-stream")}

    @staticmethod
    def _decode(response):
        if response.is_redirect:
            raise BridgeError("School Manager повернув перенаправлення; запит не повторювався")
        if response.status_code >= 400:
            if response.status_code == 404:
                raise BridgeError("Запис або функцію не знайдено. Для MCP потрібна оновлена версія School Manager")
            try:
                detail = response.json().get("detail", "")
            except (ValueError, AttributeError):
                detail = ""
            if not isinstance(detail, str):
                detail = "Перевірте параметри запиту"
            raise BridgeError(f"School Manager ({response.status_code}): {detail[:600]}")
        try:
            return response.json()
        except ValueError:
            raise BridgeError("School Manager повернув несумісну відповідь. Запустіть оновлену програму") from None

    def status(self):
        try:
            identity = self.request("GET", "/api/assistant/status")
            return {"online": True, **identity, "health": self.request("GET", "/health"),
                    "notifications": self.request("GET", "/api/system/notifications"),
                    "local_time": datetime.now(zone(DEFAULT_TIMEZONE)).isoformat(),
                    "timezone": DEFAULT_TIMEZONE}
        except BridgeError as error:
            return {"online": False, "error": str(error), "url": self.base_url}

    def get_item(self, identity: str):
        return self.request("GET", "/api/tasks/" + item_id(identity))

    def create(self, title: str, request_id: str, kind: str = "task", day: str | None = None,
               clock: str | None = None, duration_minutes: int = 60, description: str = "",
               timezone_name: str = DEFAULT_TIMEZONE, remind_before_minutes: int | None = None,
               group_id: int | None = None, fold: int | None = None, options: dict | None = None,
               end_day: str | None = None):
        identity = item_id(request_id)
        if not title.strip() or len(title) > 240 or len(description) > 20000:
            raise BridgeError("Вкажіть назву до 240 символів і опис до 20000 символів")
        if kind not in {"task", "event"} or not 1 <= duration_minutes <= 1440:
            raise BridgeError("Вкажіть task/event і тривалість від 1 до 1440 хвилин")
        if kind == "event" and not day:
            raise BridgeError("Для події потрібна дата")
        if remind_before_minutes is not None and (not day or not clock or not 0 <= remind_before_minutes <= 10080):
            raise BridgeError("Для нагадування потрібні дата, час і відступ від 0 до 10080 хвилин")
        tz = zone(timezone_name)
        at = local_time(day, clock, timezone_name, fold) if day and clock else None
        if clock and not day:
            raise BridgeError("Для часу потрібна дата")
        if end_day and (clock or not day):
            raise BridgeError("end_day використовується лише для події на весь день; для події з часом задайте duration_minutes")
        if day and not clock:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or (end_day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_day)):
                    raise ValueError()
                date.fromisoformat(day)
                if end_day and date.fromisoformat(end_day) < date.fromisoformat(day):
                    raise ValueError()
            except ValueError:
                raise BridgeError("Вкажіть дату YYYY-MM-DD") from None
        end = (at.astimezone(timezone.utc) + timedelta(minutes=duration_minutes)).astimezone(tz) if at else None
        reminder_at = (at.astimezone(timezone.utc) - timedelta(minutes=remind_before_minutes)).astimezone(tz) if remind_before_minutes is not None else None
        if reminder_at and reminder_at.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            raise BridgeError("Час нагадування вже минув. Уточніть майбутню дату або відступ")
        # The app uses one fold for both endpoints; reject intervals it cannot represent.
        if end and local_time(end.date().isoformat(), end.strftime("%H:%M"), timezone_name, at.fold).astimezone(timezone.utc) != end.astimezone(timezone.utc):
            raise BridgeError("Інтервал перетинає повторення години. Виберіть інший початок або тривалість")
        payload = {"title": title.strip(), "request_id": identity, "kind": kind,
                   "category": "lesson" if kind == "event" else "preparation", "description": description,
                   "timezone": timezone_name, "date": day, "time": clock, "fold": at.fold if at else fold,
                   "end_date": end.date().isoformat() if end else end_day,
                   "end_time": end.strftime("%H:%M") if end else None, "group_id": group_id,
                   "google_enabled": False}
        if options:
            allowed = {"category", "parent_id", "group_id", "google_enabled", "google_calendar_id",
                       "location", "recurrence", "attendees", "meet_requested"}
            if set(options) - allowed:
                raise BridgeError("Невідомі додаткові поля події")
            payload.update(options)
        saved = self.request("POST", "/api/tasks", json=payload)
        keys = ("title", "kind", "date", "time", "end_date", "end_time", "timezone", "description", "group_id")
        if (saved.get("deleted_at") or saved.get("status", "open") != "open" or
                any(saved.get(key) != payload.get(key) for key in keys if payload.get(key) is not None)):
            raise BridgeError(f"request_id вже належить іншому або зміненому запису {saved['id']}. Перегляньте його; для нової дії створіть новий UUID")
        if reminder_at:
            try:
                saved = self.set_reminder(saved["id"], saved["revision"], reminder_at.date().isoformat(),
                                          reminder_at.strftime("%H:%M"), reminder_at.fold)
            except BridgeError as error:
                return {"ok": False, "partial": True, "item": saved, "request_id": identity,
                        "error": "Подію збережено, нагадування не підтверджено: " + str(error),
                        "next_action": "Перевірте get_item і повторіть set_reminder; не створюйте другу подію"}
        return {"ok": True, "item": saved, "request_id": identity,
                "notification_note": "Для системного сповіщення School Manager має працювати, а сповіщення бути увімкненими" if reminder_at else None}

    def set_reminder(self, identity: str, revision: int, day: str, clock: str, fold: int | None = None, channel="system"):
        identity = item_id(identity)
        saved = self.get_item(identity)
        at = local_time(day, clock, saved["timezone"], fold)
        if at.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            raise BridgeError("Виберіть майбутній час нагадування")
        if channel not in {"system", "telegram"}:
            raise BridgeError("Невідомий канал нагадування")
        return self.request("POST", f"/api/tasks/{identity}/reminders", json={
            "revision": revision, "channel": channel, "date": day, "time": clock, "fold": at.fold})

    def list_items(self, start=None, end=None, query="", bucket="calendar", completed=False, limit=50, offset=0,
                   category="", source="", timezone_name=DEFAULT_TIMEZONE):
        if bucket not in {"calendar", "all", "undated", "overdue", "reminders", "trash"} or not 1 <= limit <= 200 or offset < 0:
            raise BridgeError("Перевірте bucket, limit (1–200) та offset")
        return self.request("GET", "/api/tasks", params={key: value for key, value in {
            "start": start, "end": end, "q": query, "bucket": bucket, "completed": completed,
            "limit": limit, "offset": offset, "timezone_name": timezone_name, "track_activity": False,
            "category": category, "source": source,
        }.items() if value is not None})

    def update(self, identity: str, revision: int, changes: dict):
        allowed = {"title", "description", "date", "time", "end_date", "end_time", "status", "fold",
                   "kind", "category", "timezone", "parent_id", "group_id", "google_enabled",
                   "google_calendar_id", "location", "recurrence", "attendees", "meet_requested"}
        if not changes or set(changes) - allowed:
            raise BridgeError("Вкажіть підтримувані поля для зміни")
        return self.request("PATCH", "/api/tasks/" + item_id(identity), json={"revision": revision, **changes})

    def reports(self, start=None, end=None, group=""):
        return self.request("GET", "/api/assistant/reports", params={key: value for key, value in {
            "start": start, "end": end, "group": group}.items() if value is not None})
