from typing import Any, Literal

try:
    from .application import READ, WRITE, DELETE, BridgeError, identifier
    from .bridge import item_id as normalize_id
    from .schemas import Upload
except ImportError:
    from application import READ, WRITE, DELETE, BridgeError, identifier
    from bridge import item_id as normalize_id
    from schemas import Upload


def register(server, app):
    @server.tool(annotations=DELETE)
    def delete_item(item_id: str, revision: int) -> dict[str, Any]:
        """Перемістити задачу/подію в кошик штатною операцією з поточною revision. Для серії це ВСЯ серія. Може синхронізувати видалення в Google."""
        return app.task_action(item_id, "delete", revision)

    @server.tool(annotations=WRITE)
    def restore_item(item_id: str, revision: int) -> dict[str, Any]:
        """Відновити запис із кошика з актуальною revision."""
        return app.task_action(item_id, "restore", revision)

    @server.tool(annotations=WRITE)
    def set_item_color(item_id: str, revision: int, color: str | None = None) -> dict[str, Any]:
        """Задати колір #RRGGBB або null для стандартного. Зберігає чинні обмеження read-only/Google."""
        return app.task_action(item_id, "color", revision, color=color)

    @server.tool(annotations=WRITE)
    def remove_reminder(item_id: str, reminder_id: str) -> dict[str, Any]:
        """Скасувати конкретне системне/особисте Telegram-нагадування через чинну чергу скасування."""
        return app.task_action(item_id, "remove_reminder", reminder_id=reminder_id)

    @server.tool(annotations=WRITE)
    def task_attachment(item_id: str, action: Literal["add", "download", "delete"],
                          upload_path: str | None = None, attachment_id: str | None = None,
                          destination: str | None = None) -> dict[str, Any]:
        """Додати/отримати/видалити файл задачі. add потребує абсолютний upload_path, download/delete — attachment_id від get_item. Не змінює інші вкладення."""
        identity = normalize_id(item_id)
        path = f"/api/tasks/{identity}/attachments"
        if action == "add":
            if not upload_path:
                raise BridgeError("Вкажіть upload_path")
            return app.http.upload("POST", path, {}, [Upload(path=upload_path)], file_field="file", timeout=120)
        if not attachment_id:
            raise BridgeError("Вкажіть attachment_id від get_item")
        path += "/" + normalize_id(attachment_id)
        if action == "download":
            return app.http.download(path, destination, "task-attachment.bin", timeout=120)
        return app.request("DELETE", path)
