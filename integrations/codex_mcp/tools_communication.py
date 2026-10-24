"""Groups, templates and Telegram operations using the existing application API."""
from typing import Any

try:
    from .application import READ, WRITE, EXTERNAL, DELETE, BridgeError, identifier, not_empty, send_day, text_match
    from .schemas import GroupChanges, ScheduledChanges, StoredFile, TemplateChanges, Upload, values
except ImportError:
    from application import READ, WRITE, EXTERNAL, DELETE, BridgeError, identifier, not_empty, send_day, text_match
    from schemas import GroupChanges, ScheduledChanges, StoredFile, TemplateChanges, Upload, values


def register(server, app):
    @server.tool(annotations=READ)
    def list_categories() -> dict[str, Any]:
        """Переглянути категорії груп. Це довільні категорії користувача, а не ролі батьків/учнів."""
        return {"items": app.request("GET", "/api/categories/")}

    @server.tool(annotations=WRITE)
    def create_category(name: str) -> dict[str, Any]:
        """Створити локальну категорію груп."""
        return app.request("POST", "/api/categories/", json={"name": name})

    @server.tool(annotations=WRITE)
    def update_category(category_id: int, name: str) -> dict[str, Any]:
        """Перейменувати локальну категорію, зберігши її групи."""
        return app.request("PUT", f"/api/categories/{identifier(category_id)}", json={"name": name})

    @server.tool(annotations=DELETE)
    def delete_category(category_id: int) -> dict[str, Any]:
        """Видалити категорію. Групи залишаються без цієї категорії."""
        return app.request("DELETE", f"/api/categories/{identifier(category_id)}")

    @server.tool(annotations=READ)
    def get_group(group_id: int) -> dict[str, Any]:
        """Прочитати конкретну групу та її Telegram ID перед зміною/відправкою."""
        return app.request("GET", f"/api/groups/{identifier(group_id)}")

    @server.tool(annotations=WRITE)
    def create_group(name: str, telegram_id: str, lesson_day: str | None = None,
                     lesson_time: str | None = None, category_id: int | None = None) -> dict[str, Any]:
        """Додати відомий Telegram-чат у локальний список. Не створює чат у Telegram."""
        return app.request("POST", "/api/groups/", json={"name": name, "telegram_id": telegram_id,
            "lesson_day": lesson_day, "lesson_time": lesson_time, "category_id": category_id})

    @server.tool(annotations=WRITE)
    def update_group(group_id: int, changes: GroupChanges) -> dict[str, Any]:
        """Змінити тільки зазначені локальні поля групи; решта полів зберігаються. Не перейменовує Telegram-чат."""
        return app.update_group(group_id, changes)

    @server.tool(annotations=DELETE)
    def delete_group(group_id: int) -> dict[str, Any]:
        """Видалити локальну групу та її залежні автоповідомлення за явним запитом. Не видаляє Telegram-чат."""
        return app.request("DELETE", f"/api/groups/{identifier(group_id)}")

    @server.tool(annotations=EXTERNAL)
    def sync_groups() -> dict[str, Any]:
        """Синхронізувати наявні Telegram-групи/канали в локальний список."""
        return app.request("POST", "/api/groups/sync", timeout=240)

    @server.tool(annotations=WRITE)
    def assign_groups_category(group_ids: list[int], category_id: int | None = None) -> dict[str, Any]:
        """Призначити категорію конкретним групам; null прибирає категорію."""
        return app.request("PATCH", "/api/groups/bulk-category", json={
            "group_ids": list(dict.fromkeys(identifier(i) for i in group_ids)), "category_id": category_id})

    @server.tool(annotations=READ)
    def list_templates(query: str = "") -> dict[str, Any]:
        """Знайти шаблони за назвою або текстом, включно з файлами й наліпками."""
        return {"items": text_match(app.request("GET", "/api/templates/"), query, "name", "text")}

    @server.tool(annotations=READ)
    def get_template(template_id: int) -> dict[str, Any]:
        """Прочитати повний збережений шаблон перед редагуванням/використанням."""
        return app.template(template_id)

    @server.tool(annotations=WRITE)
    def create_template(name: str, text: str = "", uploads: list[Upload] | None = None,
                         stored_files: list[StoredFile] | None = None, stickers: list[dict] | None = None) -> dict[str, Any]:
        """Зберегти шаблон з оформленим Telegram-текстом, емодзі, вкладеннями та наліпками. Сам текст пише Codex. Не надсилає повідомлення."""
        return app.write_template(name, text, uploads=uploads or (), stored=stored_files or (), stickers=stickers)

    @server.tool(annotations=WRITE)
    def update_template(template_id: int, changes: TemplateChanges,
                         uploads: list[Upload] | None = None, stored_files: list[StoredFile] | None = None) -> dict[str, Any]:
        """Змінити шаблон. Невказані текст, назва, наліпки й файли зберігаються. keep_file_ids задає повний бажаний порядок наявних файлів; [] видаляє їх. Не надсилає повідомлення."""
        return app.write_template(identity=template_id, changes=changes, uploads=uploads or (), stored=stored_files or ())

    @server.tool(annotations=WRITE)
    def duplicate_template(template_id: int, name: str, text: str | None = None) -> dict[str, Any]:
        """Скопіювати шаблон разом із файлами та наліпками; за потреби замінити текст."""
        return app.duplicate_template(template_id, name, text)

    @server.tool(annotations=DELETE)
    def delete_template(template_id: int) -> dict[str, Any]:
        """Видалити шаблон і його вкладення за явним запитом."""
        return app.request("DELETE", f"/api/templates/{identifier(template_id)}")

    @server.tool(annotations=EXTERNAL)
    def polish_text(text: str, context: str = "message") -> dict[str, Any]:
        """Викликати Magic-редактор School Manager через налаштований Google AI. context=message/template/auto_message. Для власного написання Codex цей виклик не потрібний."""
        if context not in {"message", "template", "auto_message"}:
            raise BridgeError("Невідомий контекст Magic")
        return app.request("POST", "/api/ai/polish-text", json={"text": text, "context": context}, timeout=90)

    @server.tool(annotations=EXTERNAL)
    def send_message(group_ids: list[int], message: str = "", uploads: list[Upload] | None = None,
                      stored_files: list[StoredFile] | None = None, stickers: list[dict] | None = None) -> dict[str, Any]:
        """РЕАЛЬНО надіслати повідомлення у точно визначені group_ids за запитом користувача. Текст/фото/відео/GIF/документи/наліпки. Повертає результат кожного чату. При тайм-ауті не повторювати автоматично: чинний API не має постійного ключа повтору."""
        return app.send(group_ids, message, uploads or (), stored_files or (), stickers)

    @server.tool(annotations=EXTERNAL)
    def send_template(template_id: int, group_ids: list[int], text: str | None = None) -> dict[str, Any]:
        """РЕАЛЬНО надіслати збережений шаблон з усіма вкладеннями/наліпками у вибрані чати. text необов'язково замінює текст лише цієї відправки."""
        source = app.template(template_id)
        stored = [StoredFile(storage="template", stored_filename=f["stored_filename"],
            filename=f["original_filename"], type=f.get("content_type") or "application/octet-stream") for f in source.get("files", [])]
        return app.send(group_ids, source.get("text", "") if text is None else text, stored=stored, stickers=source.get("stickers", []))

    @server.tool(annotations=READ)
    def list_scheduled_messages(query: str = "", group_id: int | None = None,
                                 active: bool | None = None) -> dict[str, Any]:
        """Знайти автоповідомлення; показує повтори, sent_count, активність і Telegram-планування. Збережено локально не означає доставлено."""
        rows = app.request("GET", "/api/auto-messages/")
        return {"items": [r for r in rows if (not query or query.casefold() in r.get("message", "").casefold()
            or query.casefold() in (r.get("group") or {}).get("name", "").casefold())
            and (group_id is None or r["group_id"] == group_id) and (active is None or bool(r["is_active"]) == active)]}

    @server.tool(annotations=EXTERNAL)
    def create_scheduled_message(group_id: int, send_day: str, send_time: str, message: str = "",
                                   repeat_count: int = 1, uploads: list[Upload] | None = None,
                                   stored_files: list[StoredFile] | None = None, stickers: list[dict] | None = None) -> dict[str, Any]:
        """Запланувати РЕАЛЬНЕ повідомлення: український день тижня або 'щодня', HH:MM у локальному часі програми. 1=одна відправка,0=безлімітні повтори. Довільна календарна дата не підтримується. Не повторювати створення після тайм-ауту без перевірки списку."""
        return app.schedule(group_id, message, send_day, send_time, repeat_count, uploads or (), stored_files or (), stickers)

    @server.tool(annotations=EXTERNAL)
    def schedule_template(template_id: int, group_id: int, send_day: str, send_time: str,
                           repeat_count: int = 1, text: str | None = None) -> dict[str, Any]:
        """Запланувати вміст шаблону з вкладеннями/наліпками у вибраний чат на день тижня й час. Не змінює шаблон."""
        source = app.template(template_id)
        stored = [StoredFile(storage="template", stored_filename=f["stored_filename"],
            filename=f["original_filename"], type=f.get("content_type") or "application/octet-stream") for f in source.get("files", [])]
        return app.schedule(group_id, source.get("text", "") if text is None else text,
            send_day, send_time, repeat_count, stored=stored, stickers=source.get("stickers", []))

    @server.tool(annotations=EXTERNAL)
    def update_scheduled_message(message_id: int, changes: ScheduledChanges) -> dict[str, Any]:
        """Змінити тільки текст, день, час або кількість повторів існуючого автоповідомлення. Вкладення, наліпки й група зберігаються за правилами чинного API."""
        payload = not_empty(changes)
        if payload.get("send_day") is not None:
            payload["send_day"] = send_day(payload["send_day"])
        return app.request("PUT", f"/api/auto-messages/{identifier(message_id)}", json=payload, timeout=180)

    @server.tool(annotations=EXTERNAL)
    def set_scheduled_message_active(message_id: int, active: bool) -> dict[str, Any]:
        """Увімкнути/призупинити конкретне автоповідомлення. Якщо потрібний стан уже встановлено, toggle не викликається."""
        return app.set_active(message_id, active)

    @server.tool(annotations=DELETE)
    def delete_scheduled_message(message_id: int) -> dict[str, Any]:
        """Видалити автоповідомлення через чинний механізм скасування. Помилки зовнішнього скасування можуть бути в журналі; локальне видалення не доводить результат у Telegram."""
        return app.request("DELETE", f"/api/auto-messages/{identifier(message_id)}", timeout=180)

    @server.tool(annotations=EXTERNAL)
    def schedule_all_active_messages() -> dict[str, Any]:
        """Повторно поставити активні автоповідомлення у планування Telegram за явним запитом. Не є перевіркою стану; може планувати багато відправок."""
        return app.request("POST", "/api/auto-messages/schedule-all", timeout=300)
