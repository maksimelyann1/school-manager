"""Adapt existing HTTP operations; no database, scheduler or report business logic."""
import json
import re
from urllib.parse import quote

try:
    from .bridge import BridgeError, item_id
    from .schemas import StoredFile, values
except ImportError:
    from bridge import BridgeError, item_id
    from schemas import StoredFile, values

READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
EXTERNAL = {**WRITE, "openWorldHint": True}
DELETE = {**EXTERNAL, "destructiveHint": True}
SECRET_KEYS = {"token", "api_hash", "api_key", "google_ai_api_key", "password", "access_token",
               "refresh_token", "id_token", "client_secret", "authorization", "session_string"}


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k.lower() not in SECRET_KEYS}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def identifier(value):
    if type(value) is not int or value < 1:
        raise BridgeError("Потрібен додатний ID запису з результатів пошуку")
    return value


def not_empty(changes):
    payload = values(changes)
    if not payload:
        raise BridgeError("Вкажіть поля, які треба змінити")
    return payload


def text_match(rows, query, *keys):
    return [row for row in rows if any(query.casefold() in str(row.get(k, "")).casefold() for k in keys)]


def send_day(value):
    allowed = {"понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя", "щодня"}
    value = value.strip().lower()
    if value in {"щодня", "щоденно", "daily"}:
        return "daily"
    if value not in allowed:
        raise BridgeError("Вкажіть українською день тижня або 'щодня'. Конкретна календарна дата для автоповідомлень не підтримується")
    return value


class Application:
    def __init__(self, client):
        self.http = client

    def request(self, method, path, **kwargs):
        return clean(self.http.request(method, path, **kwargs))

    def template(self, identity):
        return self.request("GET", f"/api/templates/{identifier(identity)}")

    def write_template(self, name=None, text=None, identity=None, changes=None, uploads=(), stored=(), stickers=None):
        if identity is None:
            if not name or not name.strip():
                raise BridgeError("Вкажіть назву шаблону")
            fields = {"name": name.strip(), "text": text or "", "stickers": stickers or []}
            path, method = "/api/templates/", "POST"
        else:
            current = self.template(identity)
            changes = values(changes) if changes else {}
            fields = {"name": current["name"], "text": current.get("text", ""),
                      "stickers": current.get("stickers", []),
                      "keep_file_ids": [f["id"] for f in current.get("files", [])]}
            fields.update({k: v for k, v in changes.items() if v is not None})
            if not changes and not uploads and not stored:
                raise BridgeError("Вкажіть зміни тексту, наліпок або вкладень")
            known = {f["id"] for f in current.get("files", [])}
            if not set(fields["keep_file_ids"]) <= known:
                raise BridgeError("keep_file_ids містить вкладення іншого шаблону")
            path, method = f"/api/templates/{identifier(identity)}", "PUT"
        if stored:
            fields["stored_files"] = [values(f) for f in stored]
        # Multipart preserves existing files and can copy stored files even without new uploads.
        return clean(self.http.upload(method, path, fields, uploads, timeout=120))

    def duplicate_template(self, identity, name, text=None):
        source = self.template(identity)
        stored = [StoredFile(storage="template", stored_filename=f["stored_filename"],
                    filename=f["original_filename"], type=f.get("content_type") or "application/octet-stream")
                  for f in source.get("files", [])]
        return self.write_template(name, source.get("text", "") if text is None else text,
                                   stored=stored, stickers=source.get("stickers", []))

    def update_group(self, identity, changes):
        identity = identifier(identity)
        current = self.request("GET", f"/api/groups/{identity}")
        payload = {k: current.get(k) for k in ("name", "telegram_id", "lesson_time", "lesson_day", "category_id")}
        payload.update(not_empty(changes))
        return self.request("PUT", f"/api/groups/{identity}", json=payload)

    def send(self, group_ids, message, uploads=(), stored=(), stickers=None):
        ids = list(dict.fromkeys(identifier(i) for i in group_ids))
        if not ids:
            raise BridgeError("Виберіть конкретні group_ids")
        known = {row["id"] for row in self.request("GET", "/api/groups/")}
        if set(ids) - known:
            raise BridgeError("Не всі одержувачі знайдені. Перечитайте список груп")
        return clean(self.http.upload("POST", "/api/messages/send", {
            "group_ids": ids, "message": message, "stored_files": [values(f) for f in stored],
            "stickers": stickers or []}, uploads, timeout=300))

    def schedule(self, group_id, message, day, clock, repeat_count, uploads=(), stored=(), stickers=None):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", clock) or repeat_count < 0:
            raise BridgeError("Вкажіть час HH:MM та repeat_count >= 0")
        self.request("GET", f"/api/groups/{identifier(group_id)}")
        return clean(self.http.upload("POST", "/api/auto-messages/", {"group_id": group_id,
            "message": message, "send_day": send_day(day), "send_time": clock, "repeat_count": repeat_count,
            "stored_files": [values(f) for f in stored], "stickers": stickers or []}, uploads, timeout=180))

    def scheduled(self, identity):
        identity = identifier(identity)
        found = next((r for r in self.request("GET", "/api/auto-messages/") if r["id"] == identity), None)
        if not found:
            raise BridgeError("Автоповідомлення не знайдено")
        return found

    def set_active(self, identity, active):
        current = self.scheduled(identity)
        if bool(current["is_active"]) == active:
            return {"changed": False, "item": current}
        result = self.request("PUT", f"/api/auto-messages/{identifier(identity)}/toggle", timeout=180)
        return {"changed": True, "result": result, "item": self.scheduled(identity)}

    def create_lesson(self, fields):
        payload = not_empty(fields)
        if not payload.get("group_name", "").strip():
            raise BridgeError("Для нового заняття вкажіть group_name")
        row = self.request("POST", "/api/parents-report/schedule", json={})
        try:
            return self.request("PATCH", f"/api/parents-report/schedule/{row['id']}", json=payload)
        except BridgeError as error:
            return {"ok": False, "partial": True, "lesson_id": row["id"], "item": row,
                    "error": str(error), "next_action": "Оновіть створений рядок через update_lesson; не створюйте ще один"}

    def report_settings(self):
        return self.request("GET", "/api/parents-report/settings")

    def report_context(self, lesson_id, lesson_date=None, absents=None, test=None, review_run_id=None):
        return {k: v for k, v in {"lesson_id": identifier(lesson_id), "lesson_date": lesson_date,
            "absents": absents, "test": test, "review_run_id": review_run_id}.items() if v is not None}

    def task_action(self, identity, action, revision=None, reminder_id=None, color=None):
        path = "/api/tasks/" + item_id(identity)
        if action == "remove_reminder":
            return self.request("DELETE", path + "/reminders/" + item_id(reminder_id))
        if type(revision) is not int or revision < 1:
            raise BridgeError("Перечитайте актуальну revision запису")
        if action == "delete":
            return self.request("DELETE", path, params={"revision": revision})
        if action == "restore":
            return self.request("POST", path + "/restore", json={"revision": revision})
        if action == "color":
            return self.request("PATCH", path + "/color", json={"revision": revision, "color": color})
        raise BridgeError("Невідома дія календаря")
