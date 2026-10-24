"""Report and schedule tools delegate to the app's existing routes unchanged."""
from datetime import date
from typing import Any, Literal
from uuid import UUID

try:
    from .application import READ, WRITE, EXTERNAL, DELETE, BridgeError, identifier, not_empty, text_match
    from .schemas import CourseLessonChanges, CourseLessonCreate, LessonChanges, ReportSettingsChanges, Upload, values
except ImportError:
    from application import READ, WRITE, EXTERNAL, DELETE, BridgeError, identifier, not_empty, text_match
    from schemas import CourseLessonChanges, CourseLessonCreate, LessonChanges, ReportSettingsChanges, Upload, values


def register(server, app):
    @server.tool(annotations=READ)
    def get_report_settings() -> dict[str, Any]:
        """Прочитати промпт, модель, автозвіти, затримки, супровідні тексти й тестовий режим. API-ключ не повертається."""
        return app.report_settings()

    @server.tool(annotations=WRITE)
    def update_report_settings(changes: ReportSettingsChanges) -> dict[str, Any]:
        """Змінити ТІЛЬКИ вказані налаштування автозвітів. prompt_template — повний новий промпт. Незазначені параметри й API-ключ зберігаються. Увімкнення автозвітів активує чинний планувальник."""
        return app.request("PUT", "/api/parents-report/settings", json=not_empty(changes))

    @server.tool(annotations=WRITE)
    def reset_report_prompt() -> dict[str, Any]:
        """Повернути стандартний промпт звітів за запитом користувача; інші налаштування зберігаються."""
        return app.request("POST", "/api/parents-report/settings/reset-prompt")

    @server.tool(annotations=READ)
    def list_pending_reports(group: str = "") -> dict[str, Any]:
        """Прочитати чинну чергу невідправлених і ручних звітів; нічого не надсилає."""
        data = app.request("GET", "/api/parents-report/pending")
        data["pending_lessons"] = text_match(data.get("pending_lessons", []), group, "group_name")
        return data

    @server.tool(annotations=READ)
    def list_report_runs(limit: int = 100, group: str = "", status: str = "",
                          start: date | None = None, end: date | None = None, run_id: int | None = None) -> dict[str, Any]:
        """Журнал звітів із текстом і помилками. Фільтри застосовуються тільки до останніх limit записів (1–500), не до всієї історії. run_id дозволяє прочитати конкретний старий запис."""
        if not 1 <= limit <= 500 or (start and end and end < start):
            raise BridgeError("Перевірте limit (1–500) і діапазон дат")
        params = {"limit": limit}
        if run_id is not None:
            params["run_id"] = identifier(run_id)
        fetched = app.request("GET", "/api/parents-report/runs", params=params)
        rows = [r for r in fetched if (not group or group.casefold() in r.get("lesson_group_name", "").casefold())
                and (not status or r["status"] == status)
                and (start is None or r["lesson_date"] >= start.isoformat())
                and (end is None or r["lesson_date"] <= end.isoformat())]
        return {"items": rows, "fetched_count": len(fetched), "limit": limit,
                "history_may_be_truncated": len(fetched) >= limit, "filter_scope": "fetched_recent_runs"}

    @server.tool(annotations=EXTERNAL)
    def prepare_report_context(lesson_id: int, lesson_date: date | None = None,
                                 absents: str | None = None, review_run_id: int | None = None) -> dict[str, Any]:
        """Перевірити тему/дату/відсутніх перед звітом через чинний preview і Logika. Може оновити дані заняття/знімок; НЕ генерує фінальний AI-текст і нічого не надсилає."""
        payload = app.report_context(lesson_id, lesson_date.isoformat() if lesson_date else None,
                                     absents, review_run_id=review_run_id)
        return app.request("POST", "/api/parents-report/preview", json=payload, timeout=240)

    @server.tool(annotations=EXTERNAL)
    def send_report(lesson_id: int, lesson_date: date | None = None, absents: str | None = None,
                      test: bool | None = None, review_run_id: int | None = None) -> dict[str, Any]:
        """РЕАЛЬНО згенерувати й надіслати звіт штатним механізмом. Зберігає перевірки заняття, відвідування, дублів і доставки. absents=null використовує чинні дані Logika; test=null зберігає режим налаштувань. test=true теж надсилає Telegram-повідомлення. Без автоматичних повторів після тайм-ауту."""
        payload = app.report_context(lesson_id, lesson_date.isoformat() if lesson_date else None, absents, test, review_run_id)
        return app.request("POST", "/api/parents-report/send", json=payload, timeout=300)

    @server.tool(annotations=EXTERNAL)
    def prepare_report_resend(run_id: int) -> dict[str, Any]:
        """Перевірити контекст повторного звіту за історичну дату через чинний resend-preview. Нічого не надсилає; може звіряти дані з Logika."""
        return app.request("GET", f"/api/parents-report/runs/{identifier(run_id)}/resend-preview", timeout=240)

    @server.tool(annotations=EXTERNAL)
    def resend_report(run_id: int, request_id: UUID, absents: str = "", use_logika_absents: bool = True) -> dict[str, Any]:
        """РЕАЛЬНО повторно відправити історичний звіт штатним механізмом після явного запиту. Новій дії — новий UUID request_id, повтору тієї самої дії — той самий UUID. Не обходить перевірки відвідування/невизначеної доставки."""
        return app.request("POST", f"/api/parents-report/runs/{identifier(run_id)}/resend", json={
            "request_id": str(request_id), "absents": absents, "use_logika_absents": use_logika_absents}, timeout=300)

    @server.tool(annotations=EXTERNAL)
    def run_due_reports() -> dict[str, Any]:
        """Запустити чинну обробку прострочених автозвітів за ЯВНИМ запитом на відправлення. Може реально надіслати кілька звітів. Для перевірки без відправлення використовуйте check_reports/list_pending_reports."""
        return app.request("POST", "/api/parents-report/auto/run-now", timeout=300)

    @server.tool(annotations=READ)
    def get_report_workbook() -> dict[str, Any]:
        """Прочитати робочий розклад і перелік курсів. Не імпортує та не надсилає дані."""
        return app.request("GET", "/api/parents-report/workbook")

    @server.tool(annotations=WRITE)
    def create_lesson(fields: LessonChanges) -> dict[str, Any]:
        """Додати рядок розкладу БАТЬКІВСЬКИХ ЗВІТІВ, не особистого календаря. Обов'язковий group_name. partial=true: рядок уже створений, завершіть через update_lesson."""
        return app.create_lesson(fields)

    @server.tool(annotations=WRITE)
    def update_lesson(lesson_id: int, changes: LessonChanges) -> dict[str, Any]:
        """Змінити конкретний рядок розкладу звітів чинною операцією. Інші поля зберігаються. last_report_date — локальний маркер, його зміна не підтверджує доставки."""
        return app.request("PATCH", f"/api/parents-report/schedule/{identifier(lesson_id)}", json=not_empty(changes), timeout=90)

    @server.tool(annotations=WRITE)
    def postpone_lesson(lesson_id: int, day: date, clock: str) -> dict[str, Any]:
        """Перенести конкретне заняття розкладу звітів на дату YYYY-MM-DD і HH:MM. Не змінює особисту подію календаря."""
        return app.request("POST", f"/api/parents-report/schedule/{identifier(lesson_id)}/postpone",
                           json={"date": day.isoformat(), "time": clock})

    @server.tool(annotations=WRITE)
    def cancel_lesson_postponement(lesson_id: int) -> dict[str, Any]:
        """Скасувати перенесення конкретного заняття розкладу звітів."""
        return app.request("DELETE", f"/api/parents-report/schedule/{identifier(lesson_id)}/postpone")

    @server.tool(annotations=WRITE)
    def set_lesson_paused(lesson_id: int, paused: bool) -> dict[str, Any]:
        """Поставити заняття/групу на паузу для звітів або відновити через чинну перевірку планувальника."""
        return app.request("PATCH", f"/api/parents-report/schedule/{identifier(lesson_id)}/pause", json={"paused": paused})

    @server.tool(annotations=DELETE)
    def delete_lesson(lesson_id: int) -> dict[str, Any]:
        """Видалити рядок розкладу звітів за явним запитом; не видаляє Telegram-чат."""
        return app.request("DELETE", f"/api/parents-report/schedule/{identifier(lesson_id)}")

    @server.tool(annotations=READ)
    def list_report_mappings() -> dict[str, Any]:
        """Прочитати наявні прив'язки навчальних груп до чатів для звітів."""
        return {"items": app.request("GET", "/api/parents-report/mappings")}

    @server.tool(annotations=WRITE)
    def set_report_mapping(lesson_group_name: str, telegram_group_id: int | None = None) -> dict[str, Any]:
        """Змінити чинну прив'язку звітів для назви навчальної групи; null прибирає її. Не додає нових ролей чатів."""
        return app.request("PUT", "/api/parents-report/mappings", json={
            "lesson_group_name": lesson_group_name, "telegram_group_id": telegram_group_id})

    @server.tool(annotations=READ)
    def list_courses(query: str = "") -> dict[str, Any]:
        """Переглянути/знайти курси бази звітів."""
        return {"items": text_match(app.request("GET", "/api/parents-report/courses"), query, "name")}

    @server.tool(annotations=READ)
    def get_course(course_id: int) -> dict[str, Any]:
        """Прочитати курс з усіма темами/матеріалами уроків без зміни курсу."""
        return app.request("GET", f"/api/assistant/courses/{identifier(course_id)}")

    @server.tool(annotations=WRITE)
    def create_course(name: str) -> dict[str, Any]:
        """Створити курс у локальній базі тем для звітів."""
        return app.request("POST", "/api/parents-report/courses", json={"name": name})

    @server.tool(annotations=WRITE)
    def update_course(course_id: int, name: str | None = None, row_order: int | None = None) -> dict[str, Any]:
        """Перейменувати/впорядкувати курс. Використовує чинне узгодження назви в пов'язаних записах."""
        payload = {k: v for k, v in {"name": name, "row_order": row_order}.items() if v is not None}
        if not payload:
            raise BridgeError("Вкажіть name або row_order")
        return app.request("PATCH", f"/api/parents-report/courses/{identifier(course_id)}", json=payload)

    @server.tool(annotations=DELETE)
    def delete_course(course_id: int) -> dict[str, Any]:
        """Видалити курс із його локальними темами за явним запитом."""
        return app.request("DELETE", f"/api/parents-report/courses/{identifier(course_id)}")

    @server.tool(annotations=WRITE)
    def create_course_lesson(course_id: int, fields: CourseLessonCreate) -> dict[str, Any]:
        """Додати тему/урок курсу: номер, код, модуль, назва, матеріал звіту, примітки."""
        return app.request("POST", f"/api/parents-report/courses/{identifier(course_id)}/lessons", json=values(fields))

    @server.tool(annotations=WRITE)
    def update_course_lesson(course_lesson_id: int, changes: CourseLessonChanges) -> dict[str, Any]:
        """Змінити тільки зазначені поля теми уроку в базі курсів."""
        return app.request("PATCH", f"/api/parents-report/course-lessons/{identifier(course_lesson_id)}", json=not_empty(changes))

    @server.tool(annotations=DELETE)
    def delete_course_lesson(course_lesson_id: int) -> dict[str, Any]:
        """Видалити конкретну тему уроку з бази курсу."""
        return app.request("DELETE", f"/api/parents-report/course-lessons/{identifier(course_lesson_id)}")

    @server.tool(annotations=EXTERNAL)
    def sync_report_source() -> dict[str, Any]:
        """Оновити вбудовану базу тем/звітів із чинного джерела. Може змінити локальні матеріали; не відправляє звіти."""
        return app.request("POST", "/api/parents-report/sync-source", timeout=240)

    @server.tool(annotations=EXTERNAL)
    def import_schedule(spreadsheet_url: str | None = None, xlsx_path: str | None = None) -> dict[str, Any]:
        """Імпортувати розклад штатним механізмом. Рівно одне: доступна Google Таблиця (spreadsheet_url) або абсолютний шлях XLSX (xlsx_path). Змінює розклад, не є попереднім переглядом."""
        if (spreadsheet_url is None) == (xlsx_path is None):
            raise BridgeError("Вкажіть рівно одне джерело імпорту")
        if spreadsheet_url:
            return app.request("POST", "/api/parents-report/import", json={"spreadsheet_url": spreadsheet_url}, timeout=240)
        if not xlsx_path.lower().endswith(".xlsx"):
            raise BridgeError("Потрібен файл .xlsx")
        return app.http.upload("POST", "/api/parents-report/import-file", {}, [Upload(path=xlsx_path)], file_field="file", timeout=240)

    @server.tool(annotations=READ)
    def export_report_workbook(destination: str | None = None) -> dict[str, Any]:
        """Експортувати розклад/базу звітів у XLSX. destination — новий абсолютний шлях; без нього файл зберігається в output/mcp. Не змінює таблиці."""
        return app.http.download("/api/parents-report/export", destination, "school-manager.xlsx", timeout=120)
