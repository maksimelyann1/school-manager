"""Existing integration, media and maintenance operations; no new desktop bridge."""
from pathlib import Path
import re
import sys
from typing import Any, Literal
from urllib.parse import quote, urlencode

try:
    from .application import READ, WRITE, EXTERNAL, DELETE, BridgeError, identifier
    from .schemas import Upload
    from .bridge import item_id
except ImportError:
    from application import READ, WRITE, EXTERNAL, DELETE, BridgeError, identifier
    from schemas import Upload
    from bridge import item_id


def register(server, app):
    @server.tool(annotations=READ)
    def get_application_info(section: Literal["overview", "startup", "version", "notifications", "autostart",
                                "cache", "interface", "telegram", "logika", "google", "update_progress"] = "overview") -> dict[str, Any]:
        """Прочитати стан вибраного розділу School Manager. telegram читає збережений стан без команди перепідключення. Секретні поля не повертаються."""
        paths = {"overview": "/api/dashboard/stats", "startup": "/api/startup", "version": "/api/system/version",
            "notifications": "/api/system/notifications", "autostart": "/api/system/autostart",
            "cache": "/api/system/cache/status", "interface": "/api/settings/interface", "telegram": "/api/settings/bot",
            "logika": "/api/logika/settings", "google": "/api/planner/google/status", "update_progress": "/api/system/update/progress"}
        return app.request("GET", paths[section], timeout=90)

    @server.tool(annotations=READ)
    def get_logs(limit: int = 100, level: str = "", module: str = "", query: str = "") -> dict[str, Any]:
        """Прочитати останні події; фільтри застосовуються лише до отриманих limit записів (1–500). Не є повною історією чи командою відправки."""
        if not 1 <= limit <= 500:
            raise BridgeError("limit має бути від 1 до 500")
        fetched = app.request("GET", "/api/logs", params={"limit": limit})
        return {"items": [r for r in fetched if (not level or r["level"].casefold() == level.casefold())
            and (not module or module.casefold() in r["module"].casefold())
            and (not query or query.casefold() in r["message"].casefold())],
            "fetched_count": len(fetched), "history_may_be_truncated": len(fetched) >= limit,
            "filter_scope": "fetched_recent_logs"}

    @server.tool(annotations=DELETE)
    def clear_logs() -> dict[str, Any]:
        """Очистити журнал подій за явним запитом; історію звітів не видаляє."""
        return app.request("DELETE", "/api/logs")

    @server.tool(annotations=WRITE)
    def set_application_setting(setting: Literal["autostart", "notifications", "sidebar_collapsed"], enabled: bool) -> dict[str, Any]:
        """Задати явний стан автозапуску, системних сповіщень або згортання меню."""
        if setting == "sidebar_collapsed":
            return app.request("PUT", "/api/settings/interface", json={"sidebar_collapsed": enabled})
        return app.request("POST", "/api/system/" + setting, json={"enabled": enabled})

    @server.tool(annotations=DELETE)
    def cleanup_cache(kind: Literal["temporary_files", "stickers"]) -> dict[str, Any]:
        """Очистити відповідний кеш штатною операцією. Не є видаленням бази/шаблонів."""
        path = "/api/system/cache/cleanup" if kind == "temporary_files" else "/api/system/cache/stickers/cleanup"
        return app.request("POST", path, timeout=120)

    @server.tool(annotations=WRITE)
    def open_data_folder() -> dict[str, Any]:
        """Відкрити папку даних School Manager у файловому менеджері."""
        return app.request("POST", "/api/system/cache/open-folder")

    @server.tool(annotations=EXTERNAL)
    def telegram_session(action: Literal["reconnect", "disconnect", "logout_full", "reset_credentials"]) -> dict[str, Any]:
        """Керувати наявною Telegram-сесією штатними командами. disconnect від'єднує тимчасово; logout_full видаляє авторизацію; reset_credentials повертає чинні стандартні параметри. Лише за відповідним запитом користувача."""
        paths = {"reconnect": "reconnect", "disconnect": "logout", "logout_full": "logout-full",
                 "reset_credentials": "credentials/reset"}
        return app.request("POST", "/api/settings/auth/" + paths[action], timeout=180)

    @server.tool(annotations=READ)
    def get_authentication_help(service: Literal["telegram", "google", "logika", "google_ai"]) -> dict[str, Any]:
        """Пояснити вхід у зовнішній сервіс без передачі паролів/кодів/ключів у чат. Для Google початок OAuth доступний через google_calendar(action=connect)."""
        instructions = {
            "telegram": "Відкрийте Налаштування School Manager → Telegram. Вхід через QR або код/2FA завершіть у програмі. Стан: get_application_info(telegram).",
            "google": "Викличте google_calendar(connect) за запитом користувача; доступ підтверджується у браузері. Стан: get_application_info(google).",
            "logika": "Введіть логін і пароль у Налаштування School Manager → Logika. Стан: get_application_info(logika).",
            "google_ai": "Додайте API-ключ у Налаштування School Manager. Промпт і модель можна змінювати через update_report_settings без читання ключа."}
        return {"service": service, "requires_user_interaction": True, "instructions": instructions[service]}

    @server.tool(annotations=EXTERNAL)
    def google_calendar(action: Literal["connect", "cancel", "disconnect", "discover", "ensure_calendar", "sync", "visibility"],
                          calendar_id: int | None = None, visible: bool | None = None) -> dict[str, Any]:
        """Керувати чинною Google Calendar інтеграцією: OAuth, список календарів, календар School Manager, синхронізація, видимість, від'єднання. connect потребує дії користувача у браузері. Не обходить права read-only."""
        if action == "visibility":
            if visible is None:
                raise BridgeError("Для visibility потрібен visible=true/false")
            return app.request("PATCH", f"/api/planner/google/calendars/{identifier(calendar_id)}", json={"visible": visible})
        paths = {"connect": "connect", "cancel": "cancel", "disconnect": "disconnect", "discover": "calendars",
                 "ensure_calendar": "calendar", "sync": "sync"}
        return app.request("POST", "/api/planner/google/" + paths[action], timeout=240)

    @server.tool(annotations=EXTERNAL)
    def logika(action: Literal["sync", "fetch_absents", "settings", "disconnect"], lesson_id: int | None = None,
                 auto_sync_enabled: bool | None = None, auto_fetch_absents: bool | None = None) -> dict[str, Any]:
        """Використати чинну Logika інтеграцію: синхронізація розкладу, отримання відсутніх, налаштування автоматизації, від'єднання. Не змінює оцінки/відвідування у Logika."""
        if action == "fetch_absents":
            return app.request("POST", f"/api/logika/fetch-absents/{identifier(lesson_id)}", timeout=180)
        if action == "settings":
            payload = {k: v for k, v in {"auto_sync_enabled": auto_sync_enabled,
                       "auto_fetch_absents": auto_fetch_absents}.items() if v is not None}
            if not payload:
                raise BridgeError("Вкажіть налаштування для зміни")
            return app.request("POST", "/api/logika/update-settings", json=payload)
        return app.request("POST", "/api/logika/" + ("sync-schedule" if action == "sync" else "disconnect"), timeout=240)

    @server.tool(annotations=EXTERNAL)
    def import_attachment_url(url: str) -> dict[str, Any]:
        """Імпортувати доступний прямий HTTP/HTTPS-файл у штатне сховище застосунку для подальшого використання. Повертає storage/stored_filename."""
        if not url.startswith(("http://", "https://")):
            raise BridgeError("Потрібне HTTP/HTTPS-посилання")
        return app.request("POST", "/api/messages/import-url", json={"url": url}, timeout=180)

    @server.tool(annotations=READ)
    def download_attachment(storage: Literal["template", "auto", "import"], stored_filename: str,
                               destination: str | None = None) -> dict[str, Any]:
        """Отримати збережене вкладення як локальний файл для перегляду; destination — новий абсолютний шлях."""
        return app.http.download("/api/files/preview", destination, Path(stored_filename).name,
                                 params={"storage": storage, "stored_filename": stored_filename}, timeout=120)

    @server.tool(annotations=WRITE)
    def open_attachment(storage: Literal["template", "auto", "import"], stored_filename: str) -> dict[str, Any]:
        """Відкрити конкретне вкладення стандартною програмою комп'ютера."""
        return app.request("POST", "/api/files/open", json={"storage": storage, "stored_filename": stored_filename})

    @server.tool(annotations=WRITE)
    def open_uploaded_file(upload_path: str) -> dict[str, Any]:
        """Передати вказаний локальний файл у штатний кеш і відкрити стандартною програмою комп'ютера. Потрібен абсолютний шлях."""
        return app.http.upload("POST", "/api/files/open-upload", {}, [Upload(path=upload_path)], file_field="file", timeout=120)

    @server.tool(annotations=READ)
    def export_application_file(kind: Literal["diagnostics", "database_backup"], destination: str | None = None) -> dict[str, Any]:
        """Зберегти штатний діагностичний файл або копію .db. database_backup — чинна копія тільки бази, без вкладень/віджетів; не повний архів і не новий механізм резервування. Файл може містити особисті дані; повертайте шлях, не його вміст."""
        route, name = ("/api/system/diagnostics/log-file", "school-manager-diagnostics.log") if kind == "diagnostics" else (
            "/api/system/backup", "school-manager-backup.db")
        return app.http.download(route, destination, name, timeout=120)

    @server.tool(annotations=DELETE)
    def restore_database(backup_path: str) -> dict[str, Any]:
        """Відновити всю локальну базу штатною операцією ЛИШЕ за явним запитом на відновлення. Потрібен .db. Використовує наявну поведінку програми; після успіху потрібен її перезапуск. Не створює новий backup-механізм."""
        if not backup_path.lower().endswith(".db"):
            raise BridgeError("Потрібен файл резервної копії .db")
        return app.http.upload("POST", "/api/system/restore", {}, [Upload(path=backup_path)], file_field="file", timeout=120)

    @server.tool(annotations=EXTERNAL)
    def application_update(action: Literal["download", "install"]) -> dict[str, Any]:
        """Завантажити/встановити вже опубліковане оновлення. download НЕ запускає інсталятор; install завершує програму й запускає встановлення лише за явним запитом. Не збирає і не публікує реліз."""
        if action == "download":
            return app.request("POST", "/api/system/update/download", json={"auto_install": False}, timeout=90)
        return app.request("POST", "/api/system/update/launch", timeout=90)

    @server.tool(annotations=EXTERNAL)
    def list_sticker_packs(short_name: str | None = None, emoji: str = "") -> dict[str, Any]:
        """Переглянути доступні набори або конкретний набір Telegram-наліпок; emoji фільтрує елементи отриманого набору."""
        if short_name is None:
            return app.request("GET", "/api/stickers/packs", timeout=120)
        if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", short_name):
            raise BridgeError("Некоректна назва набору наліпок")
        result = app.request("GET", "/api/stickers/packs/" + quote(short_name, safe=""), timeout=120)
        if emoji:
            for key in ("stickers", "items"):
                if isinstance(result.get(key), list):
                    result[key] = [s for s in result[key] if emoji in str(s.get("emoji", ""))]
        return result

    @server.tool(annotations=EXTERNAL)
    def sticker_cache(warmup: bool = False) -> dict[str, Any]:
        """Перевірити стан кешу наліпок або запустити штатний прогрів (warmup=true)."""
        return app.request("POST" if warmup else "GET", "/api/stickers/warmup")

    @server.tool(annotations=EXTERNAL)
    def download_sticker(file_id: str, kind: Literal["thumb", "animation", "file"] = "thumb",
                            mime_type: str = "image/webp", pack: str = "", document_id: str = "",
                            destination: str | None = None) -> dict[str, Any]:
        """Отримати прев'ю/анімацію/файл конкретної наліпки як локальний артефакт."""
        extension = ".png" if kind == "thumb" else ".gif" if mime_type == "application/x-tgsticker" else ".webm" if mime_type == "video/webm" else ".webp"
        return app.http.download("/api/stickers/" + kind, destination, "sticker" + extension,
            params={"file_id": file_id, "mime_type": mime_type, "pack": pack, "document_id": document_id}, timeout=180)

    @server.tool(annotations=WRITE)
    def open_application_view(view: Literal["overview", "reports", "report_runs", "calendar", "overdue", "reminders", "scheduled"],
                                record_id: str | None = None, day: str | None = None) -> dict[str, Any]:
        """Відкрити підтримуваний розділ штатним schoolmanager-протоколом. Не керує вікном/віджетами й не додає desktop-міст. Протокол має бути зареєстрований програмою."""
        identity = app.request("GET", "/api/assistant/status")
        params = {}
        if view == "overview":
            path = "/"
        elif view in {"reports", "report_runs"}:
            path = "/parents-report"
            params["tab"] = "runs" if view == "report_runs" else "pending"
            if record_id:
                params["run_id" if view == "report_runs" else "lesson_id"] = identifier(int(record_id))
        elif view == "scheduled":
            path = "/auto-messages"
            if record_id:
                params["message_id"] = identifier(int(record_id))
        else:
            path = "/tasks"
            if view != "calendar":
                params["bucket"] = view
            if record_id:
                params["item_id"] = item_id(record_id)
            if day:
                from datetime import date
                params["date"] = date.fromisoformat(day).isoformat()
        protocol = "schoolmanager" if identity.get("runtime") == "installed" else "schoolmanager-dev"
        uri = f"{protocol}://open{path}" + ("?" + urlencode(params) if params else "")
        if sys.platform != "win32":
            return {"opened": False, "uri": uri, "message": "Відкрийте посилання на комп'ютері з зареєстрованим протоколом School Manager"}
        import os
        os.startfile(uri)
        return {"requested": True, "uri": uri, "note": "Запит навігації передано системному протоколу; це не перевірка фактичного відображення"}
