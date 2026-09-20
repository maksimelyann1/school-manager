import asyncio
import io
import json
import os
import re
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from logger import log_event
from models import (
    AutoMessage,
    Group,
    ParentReportCourse,
    ParentReportCourseLesson,
    ParentReportGroupMap,
    ParentReportLesson,
    ParentReportNotification,
    ParentReportRun,
    ParentReportSettings,
)
from pyrogram_client import pyrogram_manager
from routers.messages import send_pyrogram_message
from routers import auto_messages
from system_notifications import show_system_notification


router = APIRouter(prefix="/parents-report", tags=["Звіт батькам"])

KYIV_TZ = ZoneInfo("Europe/Kyiv")
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_REPORT_DELAY_MINUTES = 10
DEFAULT_REPORT_NOTIFICATION_DELAY_MINUTES = 0
DEFAULT_DURATION_MINUTES = 90
DEFAULT_ABSENT_FOLLOWUP_DELAY_MINUTES = 5
DEFAULT_ABSENT_FOLLOWUP_BEFORE_LESSON_TIME = "20:00"
AUTO_REPORT_JOB_ID = "parents_report_auto_sender"
REPORT_NOTIFICATION_JOB_ID = "parents_report_system_notifications"
AUTO_REPORT_INTERVAL_SECONDS = 60
SOURCE_SHEET_ID_PARTS = ("1KXiiGr1z4", "Xpi039gYgD", "Zj9twSm5XONl", "HaymDsrOzKhE")
SOURCE_CACHE_TTL = timedelta(hours=6)
_source_course_lessons_cache: dict[str, list[dict[str, Any]]] = {}
_source_cache_loaded_at: datetime | None = None
_ai_report_lock = asyncio.Lock()

REPORT_LOG_MODULE = "ParentsReport"

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

MODEL_OPTIONS = [
    {"label": "Gemini 3.5 Flash", "value": "gemini-3.5-flash"},
    {"label": "Gemini 3 Flash", "value": "gemini-3-flash-preview"},
    {"label": "Gemini 3.1 Flash Lite", "value": "gemini-3.1-flash-lite"},
    {"label": "Gemini 2.5 Flash", "value": "gemini-2.5-flash"},
    {"label": "Gemini 2.5 Flash Lite", "value": "gemini-2.5-flash-lite"},
]


def _log_report_issue(level: str, message: str):
    log_event(level.upper(), REPORT_LOG_MODULE, message)


def _http_level(status_code: int) -> str:
    return "ERROR" if status_code >= 500 else "WARNING"


def _raise_report_http(
    status_code: int,
    detail: str,
    *,
    action: str = "Звіт батькам",
    lesson: ParentReportLesson | None = None,
    log: bool = True,
):
    if log:
        target = f" для '{lesson.group_name}'" if lesson else ""
        _log_report_issue(_http_level(status_code), f"{action}{target}: {detail}")
    raise HTTPException(status_code=status_code, detail=detail)

DEFAULT_PROMPT_TEMPLATE = """Ти — вчитель, що пише звіти батькам у Telegram. Твоє завдання: на основі вхідних даних заповнити шаблон.

ВИМОГИ: Тон професійний, але теплий. Уникай порожніх полів та прочерків, зберігай відступи і переноси.

ВХІДНІ ДАНІ:
Відсутні: {absents}

МАТЕРІАЛ УРОКУ ДЛЯ ЗВІТУ:
{topic}

ЛОГІКА "ВІДСУТНІ":
Якщо в полі "Відсутні" є імена, виведи блок про відсутніх з їхніми іменами.

Якщо поле "Відсутні" порожнє, повністю видали блок про відсутніх зі звіту.

ШАБЛОН ЗВІТУ:
Доброго дня👋, шановні батьки!👨🏼👩🏻‍🦱

[БЛОК ВІДСУТНІХ:
⁉️На занятті були відсутні: (імена).

Прошу наступного заняття приєднатися цих студентів на 30 хвилин раніше.]

❗ВАЖЛИВО❗ Якщо в учнів виникають запитання щодо виконання домашнього завдання чи не зрозуміла попередня тема, прошу приєднуватися їх раніше до заняття.

1️⃣Тема уроку: (назва теми)

2️⃣Мета: (коротко сформулюй мету)

3️⃣Повторення: (що повторили)

4️⃣Ми вивчили (що вивчили), тепер краще можемо (результат), знаємо як (навички), вміємо та застосовуємо (практика). Це допоможе нам у (майбутнє).

💻ДОМАШНЯ ПРАКТИКА:🖱️ 👁️‍🗨️на платформі зробити завдання які не встигли на уроці. ❕ДЗ виконати до наступного заняття. Запитання — в чат. 💬 Завжди готовий відповісти😀 📈Продуктивного тижня, 🖖🏻до зустрічі!"""

LEGACY_PROMPT_PREFIX = "Ти помічник навчальної школи."

DAY_ALIASES = {
    "пн": "ПН",
    "понеділок": "ПН",
    "вт": "ВТ",
    "вівторок": "ВТ",
    "вторник": "ВТ",
    "ср": "СР",
    "середа": "СР",
    "чт": "ЧТ",
    "четвер": "ЧТ",
    "пт": "ПТ",
    "п'ятниця": "ПТ",
    "пятниця": "ПТ",
    "пятница": "ПТ",
    "сб": "СБ",
    "субота": "СБ",
    "нд": "НД",
    "неділя": "НД",
    "вс": "НД",
}

WEEKDAY_MAP = {
    "ПН": 0,
    "ВТ": 1,
    "СР": 2,
    "ЧТ": 3,
    "ПТ": 4,
    "СБ": 5,
    "НД": 6,
}

SCHEDULE_HEADERS = [
    "Група",
    "День",
    "Час",
    "Курс",
    "Урок",
    "Кількість проведених уроків",
    "Дата звіту",
    "Відсутні",
    "Тема уроку",
    "Тривалість",
]

COURSE_HEADERS = ["Номер уроку", "Модуль", "Тема уроку", "Звіт", "Примітки до уроку"]

AUTO_SEND_DAY_BY_WEEKDAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UKRAINIAN_DAY_ACCUSATIVE = ["Понеділок", "Вівторок", "Середу", "Четвер", "П'ятницю", "Суботу", "Неділю"]

DEFAULT_ABSENT_FOLLOWUP_TEMPLATE = """Вітаю, шановні батьки!😊

👋Чекаємо на урок наших розумників у {next_lesson_day} о {next_lesson_time_dot} ⏰ за графіком !!

❗️На відпрацювання об {makeup_time}🔔 {absents}!

✅Прошу поставте ➕ або лайк 👍, що ознайомились та будете на уроці👩‍💻

✅ Прохання попереджати, якщо когось з дітей не буде😊

Всім гарних вихідних 🍰☕️"""

DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE = """Вітаю, шановні батьки!😊

👋Чекаємо на урок наших розумників завтра у {next_lesson_day} о {next_lesson_time_dot} ⏰ за графіком !!

🇺🇦 Одягайте вишиванку або білу футболку - буде тематичний урок.

✅Прошу поставте ➕ або лайк 👍, що ознайомились та будете  на  уроці👩‍💻

✅ Прохання попереджати, якщо когось з дітей не буде😊

Всім гарних вихідних  🦋"""


class ReportSettingsUpdate(BaseModel):
    google_ai_api_key: str | None = None
    google_ai_model: str | None = None
    prompt_template: str | None = None
    auto_reports_enabled: bool | None = None
    report_delay_minutes: int | None = None
    report_notifications_enabled: bool | None = None
    report_notification_delay_minutes: int | None = None
    absent_followup_enabled: bool | None = None
    absent_followup_schedule_mode: str | None = None
    absent_followup_delay_minutes: int | None = None
    absent_followup_before_lesson_time: str | None = None
    absent_followup_template: str | None = None
    no_absents_followup_template: str | None = None
    default_duration_minutes: int | None = None
    test_mode: bool | None = None


class ImportRequest(BaseModel):
    spreadsheet_url: str | None = None


class MappingUpdate(BaseModel):
    lesson_group_name: str
    telegram_group_id: int | None = None


class ScheduleUpdate(BaseModel):
    group_name: str | None = None
    telegram_group_id: int | None = None
    day: str | None = None
    start_time: str | None = None
    course: str | None = None
    lesson_code: str | None = None
    lesson_count: str | None = None
    lesson_title: str | None = None
    lesson_topic_detail: str | None = None
    lesson_report_text: str | None = None
    topic: str | None = None
    duration_minutes: int | None = None
    last_report_date: str | None = None
    absents: str | None = None
    row_order: int | None = None


class CourseCreate(BaseModel):
    name: str


class CourseUpdate(BaseModel):
    name: str | None = None
    row_order: int | None = None


class CourseLessonCreate(BaseModel):
    lesson_count: int | None = None
    lesson_code: str | None = ""
    module: str | None = ""
    lesson_title: str | None = ""
    lesson_topic_detail: str | None = ""
    lesson_report_text: str | None = ""
    notes: str | None = ""


class CourseLessonUpdate(BaseModel):
    lesson_count: int | None = None
    lesson_code: str | None = None
    module: str | None = None
    lesson_title: str | None = None
    lesson_topic_detail: str | None = None
    lesson_report_text: str | None = None
    notes: str | None = None
    row_order: int | None = None


class SendReportRequest(BaseModel):
    lesson_id: int
    absents: str | None = ""
    test: bool | None = None


class PostponeLessonRequest(BaseModel):
    date: str
    time: str


def _now_iso() -> str:
    return datetime.now(KYIV_TZ).isoformat()


def _today_kyiv() -> date:
    return datetime.now(KYIV_TZ).date()


def _normalize_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _settings_response(settings: ParentReportSettings) -> dict[str, Any]:
    return {
        "id": settings.id,
        "google_ai_api_key_set": bool(settings.google_ai_api_key),
        "google_ai_api_key_masked": "•" * len(settings.google_ai_api_key or "") if settings.google_ai_api_key else "",
        "google_ai_model": settings.google_ai_model or DEFAULT_MODEL,
        "google_ai_model_options": MODEL_OPTIONS,
        "prompt_template": settings.prompt_template or DEFAULT_PROMPT_TEMPLATE,
        "auto_reports_enabled": bool(settings.auto_reports_enabled),
        "report_delay_minutes": (
            settings.report_delay_minutes
            if settings.report_delay_minutes is not None
            else DEFAULT_REPORT_DELAY_MINUTES
        ),
        "report_notifications_enabled": bool(getattr(settings, "report_notifications_enabled", 1)),
        "report_notification_delay_minutes": (
            settings.report_notification_delay_minutes
            if getattr(settings, "report_notification_delay_minutes", None) is not None
            else DEFAULT_REPORT_NOTIFICATION_DELAY_MINUTES
        ),
        "absent_followup_enabled": bool(getattr(settings, "absent_followup_enabled", 1)),
        "absent_followup_schedule_mode": (
            getattr(settings, "absent_followup_schedule_mode", None) or "after_report"
        ),
        "absent_followup_delay_minutes": (
            settings.absent_followup_delay_minutes
            if getattr(settings, "absent_followup_delay_minutes", None) is not None
            else DEFAULT_ABSENT_FOLLOWUP_DELAY_MINUTES
        ),
        "absent_followup_before_lesson_time": (
            getattr(settings, "absent_followup_before_lesson_time", None)
            or DEFAULT_ABSENT_FOLLOWUP_BEFORE_LESSON_TIME
        ),
        "absent_followup_template": (
            getattr(settings, "absent_followup_template", None)
            or DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
        ),
        "no_absents_followup_template": (
            getattr(settings, "no_absents_followup_template", None)
            or DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE
        ),
        "default_duration_minutes": (
            settings.default_duration_minutes
            if settings.default_duration_minutes is not None
            else DEFAULT_DURATION_MINUTES
        ),
        "test_mode": bool(settings.test_mode),
        "updated_at": settings.updated_at,
    }


def _is_legacy_default_prompt(value: str | None) -> bool:
    prompt = str(value or "").strip()
    if prompt.startswith(LEGACY_PROMPT_PREFIX):
        return True
    return bool(prompt) and re.sub(r"\s+", "", prompt) == re.sub(r"\s+", "", DEFAULT_PROMPT_TEMPLATE)


def _get_or_create_settings(db: Session) -> ParentReportSettings:
    settings = db.query(ParentReportSettings).first()
    if settings:
        if not settings.google_ai_model:
            settings.google_ai_model = DEFAULT_MODEL
        if not settings.prompt_template or _is_legacy_default_prompt(settings.prompt_template):
            settings.prompt_template = DEFAULT_PROMPT_TEMPLATE
        if settings.report_delay_minutes is None:
            settings.report_delay_minutes = DEFAULT_REPORT_DELAY_MINUTES
        if getattr(settings, "report_notifications_enabled", None) is None:
            settings.report_notifications_enabled = 1
        if getattr(settings, "report_notification_delay_minutes", None) is None:
            settings.report_notification_delay_minutes = DEFAULT_REPORT_NOTIFICATION_DELAY_MINUTES
        if getattr(settings, "absent_followup_enabled", None) is None:
            settings.absent_followup_enabled = 1
        if not getattr(settings, "absent_followup_schedule_mode", None):
            settings.absent_followup_schedule_mode = "after_report"
        if getattr(settings, "absent_followup_delay_minutes", None) is None:
            settings.absent_followup_delay_minutes = DEFAULT_ABSENT_FOLLOWUP_DELAY_MINUTES
        if not getattr(settings, "absent_followup_before_lesson_time", None):
            settings.absent_followup_before_lesson_time = DEFAULT_ABSENT_FOLLOWUP_BEFORE_LESSON_TIME
        if not getattr(settings, "absent_followup_template", None):
            settings.absent_followup_template = DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
        if not getattr(settings, "no_absents_followup_template", None):
            settings.no_absents_followup_template = DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE
        if settings.default_duration_minutes is None:
            settings.default_duration_minutes = DEFAULT_DURATION_MINUTES
        return settings

    settings = ParentReportSettings(
        google_ai_model=DEFAULT_MODEL,
        prompt_template=DEFAULT_PROMPT_TEMPLATE,
        auto_reports_enabled=0,
        report_delay_minutes=DEFAULT_REPORT_DELAY_MINUTES,
        report_notifications_enabled=1,
        report_notification_delay_minutes=DEFAULT_REPORT_NOTIFICATION_DELAY_MINUTES,
        absent_followup_enabled=1,
        absent_followup_schedule_mode="after_report",
        absent_followup_delay_minutes=DEFAULT_ABSENT_FOLLOWUP_DELAY_MINUTES,
        absent_followup_before_lesson_time=DEFAULT_ABSENT_FOLLOWUP_BEFORE_LESSON_TIME,
        absent_followup_template=DEFAULT_ABSENT_FOLLOWUP_TEMPLATE,
        no_absents_followup_template=DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE,
        default_duration_minutes=DEFAULT_DURATION_MINUTES,
        test_mode=0,
        updated_at=_now_iso(),
    )
    db.add(settings)
    db.flush()
    return settings


def _extract_spreadsheet_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Вкажіть посилання на Google Таблицю")
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", raw):
        return raw
    raise HTTPException(status_code=400, detail="Не вдалося визначити ID Google Таблиці з посилання")


def _export_url(spreadsheet_url: str) -> str:
    sheet_id = _extract_spreadsheet_id(spreadsheet_url)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"


def _source_sheet_id() -> str:
    return "".join(SOURCE_SHEET_ID_PARTS)


def _source_export_url() -> str:
    return f"https://docs.google.com/spreadsheets/d/{_source_sheet_id()}/export?format=xlsx"


async def _download_sheet_xlsx(spreadsheet_url: str) -> str:
    target = tempfile.NamedTemporaryFile(prefix="school_manager_report_", suffix=".xlsx", delete=False)
    target_path = target.name
    target.close()

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(_export_url(spreadsheet_url))
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Google Таблиця недоступна для експорту XLSX (HTTP {response.status_code})",
                )
            content_type = response.headers.get("content-type", "")
            if "spreadsheet" not in content_type and "octet-stream" not in content_type:
                raise HTTPException(
                    status_code=400,
                    detail="Google повернув не XLSX-файл. Перевірте доступ до таблиці.",
                )

        with open(target_path, "wb") as destination:
            destination.write(response.content)
        return target_path
    except Exception:
        try:
            os.remove(target_path)
        except OSError:
            pass
        raise


async def _download_source_xlsx() -> str:
    target = tempfile.NamedTemporaryFile(prefix="school_manager_report_source_", suffix=".xlsx", delete=False)
    target_path = target.name
    target.close()

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(_source_export_url())
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"База звітів недоступна для оновлення (HTTP {response.status_code})",
                )
            content_type = response.headers.get("content-type", "")
            if "spreadsheet" not in content_type and "octet-stream" not in content_type:
                raise HTTPException(
                    status_code=400,
                    detail="Джерело звітів повернуло не XLSX-файл. Перевірте доступ до інтернету.",
                )

        with open(target_path, "wb") as destination:
            destination.write(response.content)
        return target_path
    except Exception:
        try:
            os.remove(target_path)
        except OSError:
            pass
        raise


def _read_shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall(f"{MAIN_NS}si"):
        text_parts = [node.text or "" for node in item.findall(f".//{MAIN_NS}t")]
        values.append("".join(text_parts))
    return values


def _relationship_targets(zip_file: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    targets = {}
    for rel in root.findall(f"{PKG_REL_NS}Relationship"):
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if not rel_id or not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = f"xl/{target}"
        targets[rel_id] = path.replace("\\", "/")
    return targets


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for letter in letters:
        value = value * 26 + (ord(letter) - ord("A") + 1)
    return max(0, value - 1)


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    value_type = cell.attrib.get("t")
    if value_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{MAIN_NS}t")).strip()

    value_node = cell.find(f"{MAIN_NS}v")
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text
    if value_type == "s":
        try:
            return shared_strings[int(raw)].strip()
        except Exception:
            return ""
    if value_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if re.fullmatch(r"-?\d+\.0+", raw):
        return raw.split(".", 1)[0]
    return raw.strip()


def _read_sheet_rows(zip_file: zipfile.ZipFile, path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(zip_file.read(path))
    rows = []
    for row_node in root.findall(f".//{MAIN_NS}sheetData/{MAIN_NS}row"):
        values: list[str] = []
        for cell in row_node.findall(f"{MAIN_NS}c"):
            ref = cell.attrib.get("r", "")
            col_index = _column_index(ref)
            while len(values) <= col_index:
                values.append("")
            values[col_index] = _cell_value(cell, shared_strings)
        while values and values[-1] == "":
            values.pop()
        rows.append(values)
    while rows and not any(str(cell).strip() for cell in rows[-1]):
        rows.pop()
    return rows


def _parse_xlsx(path: str) -> dict[str, list[list[str]]]:
    with zipfile.ZipFile(path) as zip_file:
        shared_strings = _read_shared_strings(zip_file)
        targets = _relationship_targets(zip_file)
        workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))

        sheets: dict[str, list[list[str]]] = {}
        for sheet in workbook.findall(f".//{MAIN_NS}sheets/{MAIN_NS}sheet"):
            title = sheet.attrib.get("name") or "Sheet"
            rel_id = sheet.attrib.get(f"{REL_NS}id")
            path = targets.get(rel_id or "")
            if path and path in zip_file.namelist():
                sheets[title] = _read_sheet_rows(zip_file, path, shared_strings)
        return sheets


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-zа-яіїєґ0-9]+", " ", str(value or "").lower()).strip()


def _find_col(headers: list[str], candidates: list[tuple[str, ...]], fallback: int | None = None) -> int | None:
    normalized = [_normalize_header(header) for header in headers]
    for idx, header in enumerate(normalized):
        for parts in candidates:
            if all(part in header for part in parts):
                return idx
    if fallback is not None and fallback >= 0:
        return fallback
    return None


def _find_report_text_col(headers: list[str]) -> int | None:
    for idx, header in enumerate(_normalize_header(header) for header in headers):
        if "звіт" in header and "дата" not in header:
            return idx
    return None


def _value(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def _normalize_day(value: str) -> str:
    raw = str(value or "").strip().lower().replace(".", "")
    return DAY_ALIASES.get(raw, str(value or "").strip().upper())


def _normalize_time(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    if re.fullmatch(r"\d+(\.\d+)?", raw):
        numeric = float(raw)
        if 0 <= numeric < 1:
            minutes = round(numeric * 24 * 60)
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

    match = re.search(r"(\d{1,2})[:.](\d{2})", raw)
    if match:
        hour = min(23, max(0, int(match.group(1))))
        minute = min(59, max(0, int(match.group(2))))
        return f"{hour:02d}:{minute:02d}"

    return raw


def _parse_int(value: str | int | None, default: int | None = None) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return default
    match = re.search(r"\d+", raw)
    if not match:
        return default
    try:
        return int(match.group(0))
    except ValueError:
        return default


def _normalize_lesson_code(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = raw.translate(str.maketrans({
        "М": "M",
        "м": "M",
        "У": "U",
        "у": "U",
        "Y": "U",
        "y": "U",
    })).upper()
    return re.sub(r"[^A-Z0-9]+", "", normalized)


def _duration_from_row(row: list[str], duration_col: int | None, default_duration: int) -> int:
    direct = _parse_int(_value(row, duration_col))
    if direct and direct >= 30:
        return direct
    for index in (10, 4):
        fallback = _parse_int(_value(row, index))
        if fallback and fallback >= 30:
            return fallback
    for cell in row[4:]:
        candidate = _parse_int(str(cell))
        if candidate and candidate >= 30:
            return candidate
    return default_duration


def _excel_serial_to_date(raw: str) -> date | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 30000 or value > 70000:
        return None
    return (datetime(1899, 12, 30) + timedelta(days=value)).date()


def _parse_report_date(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    serial_date = _excel_serial_to_date(raw)
    if serial_date:
        return serial_date
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def _format_display_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _format_run_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KYIV_TZ)
    return parsed.astimezone(KYIV_TZ)


def _parse_postpone_start(date_value: str, time_value: str) -> datetime:
    raw_date = str(date_value or "").strip()
    raw_time = _normalize_time(time_value or "")
    try:
        lesson_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        hour, minute = [int(part) for part in raw_time.split(":", 1)]
        return datetime.combine(lesson_date, time(hour, minute), tzinfo=KYIV_TZ)
    except Exception as error:
        raise HTTPException(status_code=400, detail="Вкажіть коректну дату і час перенесеного уроку") from error


def _find_schedule_sheet(sheets: dict[str, list[list[str]]]) -> tuple[str, list[list[str]]]:
    for title, rows in sheets.items():
        if title.strip().lower() == "розклад груп":
            return title, rows
    for title, rows in sheets.items():
        if "розклад" in title.strip().lower():
            return title, rows
    raise HTTPException(status_code=400, detail="У таблиці не знайдено лист 'Розклад груп'")


def _find_course_list_sheet(sheets: dict[str, list[list[str]]]) -> tuple[str, list[list[str]]] | None:
    for title, rows in sheets.items():
        if title.strip().lower() == "курс та групу":
            return title, rows
    for title, rows in sheets.items():
        normalized = title.strip().lower()
        if "курс" in normalized and "груп" in normalized:
            return title, rows
    return None


def _extract_course_names(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for index, row in enumerate(rows, start=1):
        name = _value(row, 0)
        if not name:
            continue
        if index == 1 and "список" in _normalize_header(name):
            continue
        result.append({
            "name": name,
            "row_order": len(result) + 1,
            "raw_data": json.dumps(row, ensure_ascii=False),
        })
    return result


def _extract_course_lessons(sheet_title: str, rows: list[list[str]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    header_index = 0
    for index, row in enumerate(rows[:10]):
        normalized = [_normalize_header(cell) for cell in row]
        if any("урок" in cell for cell in normalized) and (
            any("назва" in cell for cell in normalized) or any("тема" in cell for cell in normalized)
        ):
            header_index = index
            break

    headers = rows[header_index]
    code_col = _find_col(headers, [("номер", "урок"), ("номер",), ("урок",)], 0)
    module_col = _find_col(headers, [("модул",)], 1)
    title_col = _find_col(headers, [("назва", "урок"), ("тема", "урок"), ("назва",)], 2)
    detail_col = _find_col(headers, [("теми", "урок"), ("теми",)], None)
    report_col = _find_report_text_col(headers)
    notes_col = _find_col(headers, [("прим",)], 4)

    lessons = []
    for source_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(str(cell).strip() for cell in row):
            continue
        lesson_code = _value(row, code_col)
        lesson_title = _value(row, title_col)
        detail = _value(row, detail_col)
        report_text = _value(row, report_col) or detail
        if not lesson_code and not lesson_title and not detail and not report_text:
            continue
        lesson_count = max(1, source_row - header_index - 1)
        lessons.append({
            "course_name": sheet_title,
            "lesson_count": lesson_count,
            "lesson_code": lesson_code,
            "module": _value(row, module_col),
            "lesson_title": lesson_title,
            "lesson_topic_detail": detail,
            "lesson_report_text": report_text,
            "notes": _value(row, notes_col),
            "source_sheet": sheet_title,
            "source_row": source_row,
            "row_order": len(lessons) + 1,
            "raw_data": json.dumps(row, ensure_ascii=False),
        })
    return lessons


def _course_lesson_lookup(course_lessons: dict[str, list[dict[str, Any]]], course: str, lesson_count: str | int | None) -> dict[str, Any] | None:
    count = _parse_int(lesson_count)
    if not course or not count:
        return None
    normalized_course = _normalize_name(course)
    for title, lessons in course_lessons.items():
        if _normalize_name(title) != normalized_course:
            continue
        for item in lessons:
            if item.get("source_row") == count + 1:
                return item
        for item in lessons:
            if item.get("lesson_count") == count:
                return item
    return None


def _course_lesson_lookup_by_code(course_lessons: dict[str, list[dict[str, Any]]], course: str, lesson_code: str | None) -> dict[str, Any] | None:
    code = _normalize_lesson_code(lesson_code)
    if not course or not code:
        return None
    normalized_course = _normalize_name(course)
    for title, lessons in course_lessons.items():
        if _normalize_name(title) != normalized_course:
            continue
        for item in lessons:
            if _normalize_lesson_code(item.get("lesson_code")) == code:
                return item
    return None


def _extract_lessons_from_sheet(
    sheet_title: str,
    rows: list[list[str]],
    default_duration: int,
    course_lessons: dict[str, list[dict[str, Any]]],
    mapping_by_group: dict[str, int | None],
) -> list[dict[str, Any]]:
    if not rows:
        return []

    header_index = 0
    for index, row in enumerate(rows[:10]):
        normalized = [_normalize_header(cell) for cell in row]
        if any("груп" in cell for cell in normalized) and any("час" in cell for cell in normalized):
            header_index = index
            break

    headers = rows[header_index]
    group_col = _find_col(headers, [("груп",)], 0)
    day_col = _find_col(headers, [("день",), ("дн",)], 1)
    time_col = _find_col(headers, [("час",), ("time",)], 2)
    course_col = _find_col(headers, [("предмет",), ("курс",)], 3)
    lesson_code_col = _find_col(headers, [("поточ", "номер"), ("номер", "урок"), ("код", "урок")], 4)
    lesson_count_col = _find_col(headers, [("кільк", "урок"), ("проведен", "урок")], 5)
    report_date_col = _find_col(headers, [("дата", "зв"), ("звіт", "дата")], 6)
    absents_col = _find_col(headers, [("відсут",), ("absent",)], 7)
    title_col = _find_col(headers, [("назва", "урок"), ("тема", "урок"), ("назва", "модул"), ("тема",)], 8)
    detail_col = _find_col(headers, [("теми", "урок")], 9)
    report_col = _find_report_text_col(headers)
    duration_col = _find_col(headers, [("тривал",), ("duration",)], 10)

    lessons = []
    for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        group_name = _value(row, group_col)
        day = _normalize_day(_value(row, day_col))
        start_time = _normalize_time(_value(row, time_col))
        course = _value(row, course_col)
        if not group_name or not day or not start_time or not course:
            continue

        lesson_count = _value(row, lesson_count_col)
        course_lesson = _course_lesson_lookup(course_lessons, course, lesson_count)
        lesson_code = (course_lesson or {}).get("lesson_code") or _value(row, lesson_code_col)
        lesson_title = (course_lesson or {}).get("lesson_title") or _value(row, title_col)
        lesson_topic_detail = (course_lesson or {}).get("lesson_topic_detail") or _value(row, detail_col)
        lesson_report_text = (
            (course_lesson or {}).get("lesson_report_text")
            or _value(row, report_col)
            or lesson_topic_detail
        )
        duration = _duration_from_row(row, duration_col, default_duration)

        lessons.append({
            "source_sheet": sheet_title,
            "source_row": offset,
            "row_order": len(lessons) + 1,
            "group_name": group_name,
            "telegram_group_id": mapping_by_group.get(_normalize_name(group_name)),
            "day": day,
            "start_time": start_time,
            "course": course,
            "lesson_code": lesson_code,
            "lesson_count": lesson_count,
            "lesson_title": lesson_title,
            "lesson_topic_detail": lesson_topic_detail,
            "lesson_report_text": lesson_report_text,
            "topic": lesson_title,
            "duration_minutes": duration,
            "last_report_date": _value(row, report_date_col),
            "absents": _value(row, absents_col),
            "raw_data": json.dumps(row, ensure_ascii=False),
        })

    return lessons


def _build_mapping_cache(db: Session) -> dict[str, int | None]:
    mapping: dict[str, int | None] = {}
    for item in db.query(ParentReportGroupMap).all():
        if item.lesson_group_name:
            mapping[_normalize_name(item.lesson_group_name)] = item.telegram_group_id
    for lesson in db.query(ParentReportLesson).all():
        if lesson.group_name and lesson.telegram_group_id:
            mapping[_normalize_name(lesson.group_name)] = lesson.telegram_group_id
    for group in db.query(Group).all():
        mapping.setdefault(_normalize_name(group.name), group.id)
    return mapping


def _extract_course_data_from_sheets(
    sheets: dict[str, list[list[str]]],
    schedule_sheet: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    ignored_sheet_names: set[str] = set()
    if schedule_sheet:
        ignored_sheet_names.add(_normalize_name(schedule_sheet))

    course_list = _find_course_list_sheet(sheets)
    if course_list:
        ignored_sheet_names.add(_normalize_name(course_list[0]))

    course_names: list[dict[str, Any]] = _extract_course_names(course_list[1]) if course_list else []
    course_name_set = {_normalize_name(item["name"]) for item in course_names}
    course_lessons: dict[str, list[dict[str, Any]]] = {}

    for title, rows in sheets.items():
        if _normalize_name(title) in ignored_sheet_names:
            continue
        lessons = _extract_course_lessons(title, rows)
        if not lessons:
            continue
        course_lessons[title] = lessons
        if _normalize_name(title) not in course_name_set:
            course_names.append({
                "name": title,
                "row_order": len(course_names) + 1,
                "raw_data": json.dumps([title], ensure_ascii=False),
            })
            course_name_set.add(_normalize_name(title))

    return course_names, course_lessons


async def _load_source_course_lessons(force: bool = False) -> dict[str, list[dict[str, Any]]]:
    global _source_course_lessons_cache, _source_cache_loaded_at

    now = datetime.now(KYIV_TZ)
    if (
        not force
        and _source_course_lessons_cache
        and _source_cache_loaded_at
        and now - _source_cache_loaded_at < SOURCE_CACHE_TTL
    ):
        return _source_course_lessons_cache

    path = await _download_source_xlsx()
    try:
        sheets = _parse_xlsx(path)
        _, course_lessons = _extract_course_data_from_sheets(sheets)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not course_lessons:
        raise HTTPException(status_code=400, detail="У базі звітів не знайдено сторінок курсів")

    _source_course_lessons_cache = course_lessons
    _source_cache_loaded_at = now
    return course_lessons


async def _source_course_lesson_lookup(
    course: str | None,
    lesson_count: str | int | None,
    force: bool = False,
) -> dict[str, Any] | None:
    if not course or not lesson_count:
        return None
    course_lessons = await _load_source_course_lessons(force=force)
    return _course_lesson_lookup(course_lessons, course, lesson_count)


async def _source_course_lesson_lookup_by_code(
    course: str | None,
    lesson_code: str | None,
    force: bool = False,
) -> dict[str, Any] | None:
    if not course or not lesson_code:
        return None
    course_lessons = await _load_source_course_lessons(force=force)
    return _course_lesson_lookup_by_code(course_lessons, course, lesson_code)


def _apply_course_item_to_lesson(lesson: ParentReportLesson, item: dict[str, Any] | ParentReportCourseLesson):
    getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
    lesson.lesson_count = str(getter("lesson_count", lesson.lesson_count) or lesson.lesson_count or "")
    lesson.lesson_code = getter("lesson_code", "") or ""
    lesson.lesson_title = getter("lesson_title", "") or ""
    lesson.lesson_topic_detail = ""
    lesson.lesson_report_text = ""
    lesson.topic = getter("lesson_title", "") or ""


def _replace_course_names_in_db(
    db: Session,
    course_names: list[dict[str, Any]],
    imported_at: str,
) -> dict[str, ParentReportCourse]:
    db.query(ParentReportCourseLesson).delete()
    db.query(ParentReportCourse).delete()

    course_by_name: dict[str, ParentReportCourse] = {}
    for item in course_names:
        course = ParentReportCourse(
            name=item["name"],
            source_sheet=item["name"],
            row_order=item["row_order"],
            raw_data=None,
            updated_at=imported_at,
        )
        db.add(course)
        db.flush()
        course_by_name[_normalize_name(course.name)] = course
    return course_by_name


def _replace_courses_in_db(
    db: Session,
    course_names: list[dict[str, Any]],
    course_lessons: dict[str, list[dict[str, Any]]],
    imported_at: str,
) -> dict[str, ParentReportCourse]:
    db.query(ParentReportCourseLesson).delete()
    db.query(ParentReportCourse).delete()

    course_by_name: dict[str, ParentReportCourse] = {}
    for item in course_names:
        course = ParentReportCourse(
            name=item["name"],
            source_sheet=item["name"],
            row_order=item["row_order"],
            raw_data=item.get("raw_data"),
            updated_at=imported_at,
        )
        db.add(course)
        db.flush()
        course_by_name[_normalize_name(course.name)] = course

    for title, rows in course_lessons.items():
        course = course_by_name.get(_normalize_name(title))
        if not course:
            course = ParentReportCourse(
                name=title,
                source_sheet=title,
                row_order=len(course_by_name) + 1,
                updated_at=imported_at,
            )
            db.add(course)
            db.flush()
            course_by_name[_normalize_name(title)] = course
        for row in rows:
            db.add(ParentReportCourseLesson(
                course_id=course.id,
                course_name=course.name,
                **{key: row[key] for key in (
                    "lesson_count",
                    "lesson_code",
                    "module",
                    "lesson_title",
                    "lesson_topic_detail",
                    "lesson_report_text",
                    "notes",
                    "source_sheet",
                    "source_row",
                    "row_order",
                    "raw_data",
                )}
            ))

    return course_by_name


def _apply_workbook_to_db(
    db: Session,
    sheets: dict[str, list[list[str]]],
    settings: ParentReportSettings,
    spreadsheet_url: str | None = None,
) -> dict[str, Any]:
    schedule_sheet, schedule_rows = _find_schedule_sheet(sheets)
    course_names, course_lessons = _extract_course_data_from_sheets(sheets, schedule_sheet)

    mapping_cache = _build_mapping_cache(db)
    lessons = _extract_lessons_from_sheet(
        schedule_sheet,
        schedule_rows,
        settings.default_duration_minutes or DEFAULT_DURATION_MINUTES,
        course_lessons,
        mapping_cache,
    )
    if not lessons:
        raise HTTPException(status_code=400, detail="У листі розкладу не знайдено уроків")

    db.query(ParentReportLesson).delete()

    imported_at = _now_iso()
    _replace_course_names_in_db(db, course_names, imported_at)

    for lesson_data in lessons:
        lesson_data["lesson_report_text"] = ""
        db.add(ParentReportLesson(**lesson_data, imported_at=imported_at))
        if not db.query(ParentReportGroupMap).filter(
            ParentReportGroupMap.lesson_group_name == lesson_data["group_name"]
        ).first():
            db.add(ParentReportGroupMap(
                lesson_group_name=lesson_data["group_name"],
                telegram_group_id=lesson_data.get("telegram_group_id"),
                updated_at=imported_at,
            ))

    if spreadsheet_url is not None:
        settings.spreadsheet_url = spreadsheet_url
    settings.updated_at = imported_at
    db.commit()

    return {
        "ok": True,
        "imported_lessons": len(lessons),
        "imported_courses": len(course_names),
        "schedule_sheet": schedule_sheet,
        "sheet_names": list(sheets.keys()),
    }


def _apply_schedule_workbook_to_db(
    db: Session,
    sheets: dict[str, list[list[str]]],
    settings: ParentReportSettings,
) -> dict[str, Any]:
    schedule_sheet, schedule_rows = _find_schedule_sheet(sheets)
    mapping_cache = _build_mapping_cache(db)
    lessons = _extract_lessons_from_sheet(
        schedule_sheet,
        schedule_rows,
        settings.default_duration_minutes or DEFAULT_DURATION_MINUTES,
        {},
        mapping_cache,
    )
    if not lessons:
        raise HTTPException(status_code=400, detail="У таблиці розкладу не знайдено уроків")

    imported_at = _now_iso()
    db.query(ParentReportLesson).delete()
    db.query(ParentReportNotification).delete()

    imported_groups: set[str] = set()
    for lesson_data in lessons:
        lesson_data["lesson_report_text"] = ""
        lesson_data["topic"] = lesson_data.get("lesson_title") or lesson_data.get("topic") or ""
        db.add(ParentReportLesson(**lesson_data, imported_at=imported_at))

        group_name = lesson_data["group_name"]
        imported_groups.add(_normalize_name(group_name))
        mapping = db.query(ParentReportGroupMap).filter(
            ParentReportGroupMap.lesson_group_name == group_name
        ).first()
        if mapping:
            if lesson_data.get("telegram_group_id"):
                mapping.telegram_group_id = lesson_data["telegram_group_id"]
            mapping.updated_at = imported_at
        else:
            db.add(ParentReportGroupMap(
                lesson_group_name=group_name,
                telegram_group_id=lesson_data.get("telegram_group_id"),
                updated_at=imported_at,
            ))

    settings.updated_at = imported_at
    db.commit()

    return {
        "ok": True,
        "imported_lessons": len(lessons),
        "imported_groups": len(imported_groups),
        "schedule_sheet": schedule_sheet,
        "sheet_names": list(sheets.keys()),
    }


def _apply_source_courses_to_db(
    db: Session,
    sheets: dict[str, list[list[str]]],
    settings: ParentReportSettings,
) -> dict[str, Any]:
    course_names, course_lessons = _extract_course_data_from_sheets(sheets)
    if not course_lessons:
        raise HTTPException(status_code=400, detail="У базі звітів не знайдено сторінок курсів")

    imported_at = _now_iso()
    global _source_course_lessons_cache, _source_cache_loaded_at
    _source_course_lessons_cache = course_lessons
    _source_cache_loaded_at = datetime.now(KYIV_TZ)

    _replace_course_names_in_db(db, course_names, imported_at)

    refreshed_lessons = 0
    for lesson in db.query(ParentReportLesson).all():
        before = (
            lesson.lesson_code,
            lesson.lesson_title,
            lesson.lesson_topic_detail,
            lesson.lesson_report_text,
            lesson.topic,
        )
        item = _course_lesson_lookup(course_lessons, lesson.course, lesson.lesson_count)
        if item:
            _apply_course_item_to_lesson(lesson, item)
        else:
            lesson.lesson_report_text = ""
        after = (
            lesson.lesson_code,
            lesson.lesson_title,
            lesson.lesson_topic_detail,
            lesson.lesson_report_text,
            lesson.topic,
        )
        if after != before:
            refreshed_lessons += 1

    settings.updated_at = imported_at
    db.commit()

    return {
        "ok": True,
        "imported_courses": len(course_names),
        "imported_course_lessons": sum(len(rows) for rows in course_lessons.values()),
        "refreshed_lessons": refreshed_lessons,
        "sheet_names": list(sheets.keys()),
    }


def _serialize_course_lesson(item: ParentReportCourseLesson) -> dict[str, Any]:
    return {
        "id": item.id,
        "course_id": item.course_id,
        "course_name": item.course_name,
        "lesson_count": item.lesson_count,
        "lesson_code": item.lesson_code or "",
        "module": item.module or "",
        "lesson_title": item.lesson_title or "",
        "lesson_topic_detail": item.lesson_topic_detail or "",
        "lesson_report_text": item.lesson_report_text or "",
        "notes": item.notes or "",
        "source_sheet": item.source_sheet or "",
        "source_row": item.source_row or 0,
        "row_order": item.row_order or item.lesson_count or 0,
    }


def _serialize_course(course: ParentReportCourse, include_lessons: bool = False) -> dict[str, Any]:
    data = {
        "id": course.id,
        "name": course.name,
        "source_sheet": course.source_sheet or course.name,
        "row_order": course.row_order or 0,
        "updated_at": course.updated_at,
    }
    if include_lessons:
        data["lessons"] = [
            _serialize_course_lesson(item)
            for item in sorted(course.lessons, key=lambda row: (row.row_order or row.lesson_count or 0, row.id))
        ]
    return data


def _serialize_lesson(lesson: ParentReportLesson, settings: ParentReportSettings | None = None) -> dict[str, Any]:
    default_duration = (settings.default_duration_minutes if settings else DEFAULT_DURATION_MINUTES) or DEFAULT_DURATION_MINUTES
    telegram_group = lesson.telegram_group
    postponed_start = _parse_iso_datetime(getattr(lesson, "postponed_start_at", None))
    return {
        "id": lesson.id,
        "source_sheet": lesson.source_sheet,
        "source_row": lesson.source_row,
        "row_order": lesson.row_order or lesson.source_row or lesson.id,
        "group_name": lesson.group_name,
        "telegram_group_id": lesson.telegram_group_id,
        "telegram_group_name": telegram_group.name if telegram_group else "",
        "day": lesson.day or "",
        "start_time": lesson.start_time or "",
        "course": lesson.course or "",
        "lesson_code": lesson.lesson_code or "",
        "lesson_count": lesson.lesson_count or "",
        "lesson_title": lesson.lesson_title or lesson.topic or "",
        "lesson_topic_detail": lesson.lesson_topic_detail or "",
        "lesson_report_text": "",
        "topic": lesson.lesson_topic_detail or lesson.topic or lesson.lesson_title or "",
        "duration_minutes": lesson.duration_minutes or default_duration,
        "last_report_date": lesson.last_report_date or "",
        "absents": lesson.absents or "",
        "is_postponed": bool(postponed_start),
        "postponed_start_at": postponed_start.isoformat() if postponed_start else "",
        "postponed_from_date": getattr(lesson, "postponed_from_date", None) or "",
        "postponed_created_at": getattr(lesson, "postponed_created_at", None) or "",
    }


def _find_course_lesson(db: Session, course_name: str | None, lesson_count: str | int | None) -> ParentReportCourseLesson | None:
    count = _parse_int(lesson_count)
    if not course_name or not count:
        return None
    normalized = _normalize_name(course_name)
    items = db.query(ParentReportCourseLesson).filter(ParentReportCourseLesson.source_row == count + 1).all()
    for item in items:
        if _normalize_name(item.course_name) == normalized:
            return item

    items = db.query(ParentReportCourseLesson).filter(ParentReportCourseLesson.lesson_count == count).all()
    for item in items:
        if _normalize_name(item.course_name) == normalized:
            return item
    return None


def _find_course_lesson_by_code(db: Session, course_name: str | None, lesson_code: str | None) -> ParentReportCourseLesson | None:
    code = _normalize_lesson_code(lesson_code)
    if not course_name or not code:
        return None
    normalized = _normalize_name(course_name)
    items = db.query(ParentReportCourseLesson).all()
    for item in items:
        if _normalize_name(item.course_name) == normalized and _normalize_lesson_code(item.lesson_code) == code:
            return item
    return None


def _refresh_lesson_from_course(db: Session, lesson: ParentReportLesson):
    item = _find_course_lesson(db, lesson.course, lesson.lesson_count)
    if not item:
        return
    _apply_course_item_to_lesson(lesson, item)


def _refresh_lesson_from_course_by_code(db: Session, lesson: ParentReportLesson):
    item = _find_course_lesson_by_code(db, lesson.course, lesson.lesson_code)
    if not item:
        return
    _apply_course_item_to_lesson(lesson, item)


async def _refresh_lesson_from_source(db: Session, lesson: ParentReportLesson, force: bool = False):
    try:
        item = await _source_course_lesson_lookup(lesson.course, lesson.lesson_count, force=force)
    except HTTPException:
        _refresh_lesson_from_course(db, lesson)
        lesson.lesson_report_text = ""
        return
    if item:
        _apply_course_item_to_lesson(lesson, item)
    else:
        lesson.lesson_report_text = ""


async def _refresh_lesson_from_source_by_code(db: Session, lesson: ParentReportLesson, force: bool = False):
    try:
        item = await _source_course_lesson_lookup_by_code(lesson.course, lesson.lesson_code, force=force)
    except HTTPException:
        _refresh_lesson_from_course_by_code(db, lesson)
        lesson.lesson_report_text = ""
        return
    if item:
        _apply_course_item_to_lesson(lesson, item)
    else:
        lesson.lesson_report_text = ""


def _lesson_schedule_context(
    lesson: ParentReportLesson,
    settings: ParentReportSettings,
    include_report_delay: bool = False,
    delay_minutes: int | None = None,
    use_postponed: bool = True,
) -> dict[str, Any] | None:
    duration = lesson.duration_minutes or settings.default_duration_minutes or DEFAULT_DURATION_MINUTES
    if delay_minutes is not None:
        delay_minutes = max(0, int(delay_minutes))
    elif include_report_delay:
        delay_minutes = (
            settings.report_delay_minutes
            if settings.report_delay_minutes is not None
            else DEFAULT_REPORT_DELAY_MINUTES
        )
    else:
        delay_minutes = 0

    postponed_start = _parse_iso_datetime(getattr(lesson, "postponed_start_at", None)) if use_postponed else None
    if postponed_start:
        start_dt = postponed_start
        lesson_date = start_dt.date()
        end_dt = start_dt + timedelta(minutes=duration)
        available_at = end_dt + timedelta(minutes=delay_minutes)
        return {
            "lesson_date": lesson_date,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "available_at": available_at,
            "duration_minutes": duration,
            "report_delay_minutes": delay_minutes,
            "is_postponed": True,
            "postponed_from_date": getattr(lesson, "postponed_from_date", None) or "",
        }

    day = _normalize_day(lesson.day or "")
    weekday = WEEKDAY_MAP.get(day)
    if weekday is None:
        return None

    start_time = _normalize_time(lesson.start_time or "")
    try:
        hour, minute = [int(part) for part in start_time.split(":", 1)]
    except Exception:
        return None

    today = _today_kyiv()
    days_ago = (today.weekday() - weekday) % 7
    lesson_date = today - timedelta(days=days_ago)
    start_dt = datetime.combine(lesson_date, time(hour, minute), tzinfo=KYIV_TZ)
    end_dt = start_dt + timedelta(minutes=duration)
    available_at = end_dt + timedelta(minutes=delay_minutes)

    return {
        "lesson_date": lesson_date,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "available_at": available_at,
        "duration_minutes": duration,
        "report_delay_minutes": delay_minutes,
        "is_postponed": False,
        "postponed_from_date": "",
    }


def _lesson_date_is_closed(lesson: ParentReportLesson, lesson_date: date) -> bool:
    report_dt = _parse_report_date(lesson.last_report_date or "")
    return bool(report_dt and report_dt >= lesson_date)


def _is_lesson_pending(
    db: Session,
    lesson: ParentReportLesson,
    settings: ParentReportSettings,
    now: datetime | None = None,
    include_report_delay: bool = False,
    delay_minutes: int | None = None,
) -> dict[str, Any] | None:
    context = _lesson_schedule_context(
        lesson,
        settings,
        include_report_delay=include_report_delay,
        delay_minutes=delay_minutes,
    )
    if context is None:
        return None

    now = now or datetime.now(KYIV_TZ)
    if now < context["available_at"]:
        return None

    if _lesson_date_is_closed(lesson, context["lesson_date"]):
        return None

    return {
        **_serialize_lesson(lesson, settings),
        "lesson_date": _format_display_date(context["lesson_date"]),
        "lesson_run_date": _format_run_date(context["lesson_date"]),
        "ended_at": context["end_dt"].isoformat(),
        "available_at": context["available_at"].isoformat(),
        "end_time": context["end_dt"].strftime("%H:%M"),
        "is_postponed": bool(context.get("is_postponed")),
        "postponed_from_date": context.get("postponed_from_date") or "",
    }


def _telegram_group_for_lesson(db: Session, lesson: ParentReportLesson) -> Group | None:
    if lesson.telegram_group_id:
        group = db.query(Group).filter(Group.id == lesson.telegram_group_id).first()
        if group:
            return group

    legacy = db.query(ParentReportGroupMap).filter(ParentReportGroupMap.lesson_group_name == lesson.group_name).first()
    if legacy and legacy.telegram_group_id:
        group = db.query(Group).filter(Group.id == legacy.telegram_group_id).first()
        if group:
            lesson.telegram_group_id = group.id
            return group

    normalized = _normalize_name(lesson.group_name)
    for group in db.query(Group).all():
        if _normalize_name(group.name) == normalized:
            lesson.telegram_group_id = group.id
            return group
    return None


def _context_values(
    lesson: ParentReportLesson,
    settings: ParentReportSettings,
    absents: str | None,
    report_source: str | None = None,
) -> dict[str, str]:
    schedule = _lesson_schedule_context(lesson, settings)
    lesson_date = schedule["lesson_date"] if schedule else _today_kyiv()
    detail_topic = report_source or lesson.lesson_report_text or lesson.lesson_topic_detail or lesson.topic or lesson.lesson_title or ""
    absents_value = (absents if absents is not None else (lesson.absents or "")).strip()
    return {
        "group": lesson.group_name or "",
        "course": lesson.course or "",
        "lesson_code": lesson.lesson_code or "",
        "lesson_count": lesson.lesson_count or "",
        "lesson_title": lesson.lesson_title or lesson.topic or "",
        "topic": detail_topic,
        "report": detail_topic,
        "absents": absents_value,
        "date": lesson_date.strftime("%d.%m.%Y"),
        "time": lesson.start_time or "",
    }


def _render_prompt(template: str, values: dict[str, str]) -> str:
    prompt = template or DEFAULT_PROMPT_TEMPLATE
    for key, value in values.items():
        prompt = prompt.replace(f"{{{key}}}", value)
    return prompt


async def _generate_ai_report(
    settings: ParentReportSettings,
    lesson: ParentReportLesson,
    absents: str | None,
    test: bool = False,
    is_auto: bool = False,
) -> str:
    api_key = (settings.google_ai_api_key or "").strip()
    if not api_key:
        _raise_report_http(
            400,
            "Додайте Google AI API key у налаштуваннях звітів",
            action="Генерація звіту",
            lesson=lesson,
            log=not is_auto,
        )

    source_item = await _source_course_lesson_lookup(lesson.course, lesson.lesson_count)
    report_source = ""
    if source_item:
        report_source = source_item.get("lesson_report_text") or source_item.get("lesson_topic_detail") or ""
        _apply_course_item_to_lesson(lesson, source_item)

    values = _context_values(lesson, settings, absents, report_source=report_source)
    prompt = _render_prompt(settings.prompt_template or DEFAULT_PROMPT_TEMPLATE, values)
    model = (settings.google_ai_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    queued_at = monotonic()
    if _ai_report_lock.locked():
        _log_report_issue("INFO", f"\u0417\u0432\u0456\u0442 \u0434\u043b\u044f '{lesson.group_name}' \u0434\u043e\u0434\u0430\u043d\u043e \u0432 \u0447\u0435\u0440\u0433\u0443 Google AI")

    try:
        async with _ai_report_lock:
            wait_seconds = round(monotonic() - queued_at, 2)
            if wait_seconds >= 0.2:
                _log_report_issue(
                    "INFO",
                    f"\u0413\u0435\u043d\u0435\u0440\u0430\u0446\u0456\u044f \u0437\u0432\u0456\u0442\u0443 \u0434\u043b\u044f '{lesson.group_name}' \u0441\u0442\u0430\u0440\u0442\u0443\u0432\u0430\u043b\u0430 \u0437 \u0447\u0435\u0440\u0433\u0438 Google AI; \u043e\u0447\u0456\u043a\u0443\u0432\u0430\u043d\u043d\u044f {wait_seconds} \u0441",
                )
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.45},
                    },
                )
    except httpx.HTTPError as error:
        detail = f"Помилка підключення до Google AI: {error}"
        if not is_auto:
            _log_report_issue("ERROR", f"Генерація звіту для '{lesson.group_name}': {detail}")
        raise HTTPException(status_code=502, detail=detail) from error

    if response.status_code >= 400:
        detail = response.text[:500]
        message = f"Google AI повернув помилку HTTP {response.status_code}: {detail}"
        _raise_report_http(
            502,
            message,
            action="Генерація звіту",
            lesson=lesson,
            log=not is_auto,
        )

    data = response.json()
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "\n".join(str(part.get("text", "")).strip() for part in parts if part.get("text")).strip()
    if not text:
        _raise_report_http(
            502,
            "Google AI не повернув текст звіту",
            action="Генерація звіту",
            lesson=lesson,
            log=not is_auto,
        )
    if test:
        return f"ТЕСТ\n{text}"
    return text


def _format_time_dot(dt: datetime) -> str:
    return dt.strftime("%H.%M")


def _render_followup_template(template: str, values: dict[str, str], default_template: str) -> str:
    message = template or default_template
    for key, value in values.items():
        message = message.replace(f"{{{key}}}", value)
    return message.strip()


def _next_lesson_start_after_report(lesson: ParentReportLesson, schedule: dict[str, Any]) -> datetime:
    start_dt = schedule["start_dt"]
    return start_dt + timedelta(days=7)


def _absent_followup_delay_minutes(settings: ParentReportSettings) -> int:
    return max(
        0,
        min(
            10080,
            int(getattr(settings, "absent_followup_delay_minutes", DEFAULT_ABSENT_FOLLOWUP_DELAY_MINUTES) or 0),
        ),
    )


def _absent_followup_plan_after_datetime(settings: ParentReportSettings) -> datetime:
    mode = getattr(settings, "absent_followup_schedule_mode", None) or "after_report"
    if mode != "after_report":
        return datetime.now(KYIV_TZ)
    return datetime.now(KYIV_TZ) + timedelta(minutes=_absent_followup_delay_minutes(settings))


def _absent_followup_target_datetime(
    settings: ParentReportSettings,
    lesson: ParentReportLesson,
    schedule: dict[str, Any],
) -> datetime:
    now = datetime.now(KYIV_TZ)
    mode = getattr(settings, "absent_followup_schedule_mode", None) or "after_report"
    plan_after = _absent_followup_plan_after_datetime(settings)
    next_start = _next_lesson_start_after_report(lesson, schedule)

    if mode == "before_next_lesson":
        send_time = _normalize_time(
            getattr(settings, "absent_followup_before_lesson_time", None)
            or DEFAULT_ABSENT_FOLLOWUP_BEFORE_LESSON_TIME
        )
        hour, minute = [int(part) for part in send_time.split(":", 1)]
        target = datetime.combine(next_start.date() - timedelta(days=1), time(hour, minute), tzinfo=KYIV_TZ)
        if target > now:
            return target

    target = datetime.combine(
        next_start.date() - timedelta(days=1),
        time(next_start.hour, next_start.minute),
        tzinfo=KYIV_TZ,
    )
    if target <= plan_after:
        return plan_after + timedelta(minutes=1)
    return target


def _absent_followup_values(
    lesson: ParentReportLesson,
    schedule: dict[str, Any],
    target_datetime: datetime,
    absents: str,
) -> dict[str, str]:
    next_start = _next_lesson_start_after_report(lesson, schedule)
    makeup_dt = next_start - timedelta(minutes=30)
    return {
        "group": lesson.group_name or "",
        "course": lesson.course or "",
        "lesson_code": lesson.lesson_code or "",
        "lesson_count": lesson.lesson_count or "",
        "lesson_title": lesson.lesson_title or lesson.topic or "",
        "absents": absents.strip(),
        "lesson_time": next_start.strftime("%H:%M"),
        "lesson_time_dot": _format_time_dot(next_start),
        "makeup_time": makeup_dt.strftime("%H:%M"),
        "makeup_time_dot": _format_time_dot(makeup_dt),
        "next_lesson_day": UKRAINIAN_DAY_ACCUSATIVE[next_start.weekday()],
        "next_lesson_date": next_start.strftime("%d.%m.%Y"),
        "next_lesson_time": next_start.strftime("%H:%M"),
        "next_lesson_time_dot": _format_time_dot(next_start),
        "send_date": target_datetime.strftime("%d.%m.%Y"),
        "send_time": target_datetime.strftime("%H:%M"),
    }


def _create_report_followup_auto_message(
    db: Session,
    lesson: ParentReportLesson,
    settings: ParentReportSettings,
    telegram_group: Group,
    schedule: dict[str, Any],
    report_run: ParentReportRun,
    absents: str,
) -> AutoMessage | None:
    clean_absents = (absents or "").strip()
    if not getattr(settings, "absent_followup_enabled", 1):
        return None

    # Очищуємо старі попередні нагадування для цього ж уроку, щоб не створювати сміття та дублікатів
    old_pending = db.query(AutoMessage).filter(
        AutoMessage.parent_report_lesson_id == lesson.id,
        AutoMessage.source.in_(["parent_report_absent_followup", "parent_report_followup"]),
    ).all()
    for old in old_pending:
        auto_messages._clear_telegram_plan_job(old.id)
        job_id = auto_messages._local_send_job_id(old.id)
        if auto_messages.scheduler.get_job(job_id):
            auto_messages.scheduler.remove_job(job_id)
        db.delete(old)
    db.flush()

    followup_type = "absent_followup" if clean_absents else "regular_followup"
    default_template = (
        DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
        if clean_absents
        else DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE
    )
    template = (
        getattr(settings, "absent_followup_template", None)
        if clean_absents
        else getattr(settings, "no_absents_followup_template", None)
    )
    target_datetime = _absent_followup_target_datetime(settings, lesson, schedule)
    plan_after_datetime = _absent_followup_plan_after_datetime(settings)
    values = _absent_followup_values(lesson, schedule, target_datetime, clean_absents)
    message = _render_followup_template(
        template or default_template,
        values,
        default_template,
    )

    auto_msg = AutoMessage(
        group_id=telegram_group.id,
        message=message,
        send_time=target_datetime.strftime("%H:%M"),
        send_day=AUTO_SEND_DAY_BY_WEEKDAY[target_datetime.weekday()],
        repeat_count=1,
        sent_count=0,
        is_active=1,
        stickers="[]",
        source="parent_report_followup",
        parent_report_lesson_id=lesson.id,
        parent_report_run_id=report_run.id,
        scheduled_target_at=target_datetime.isoformat(timespec="minutes"),
        metadata_json=json.dumps(
            {
                "type": followup_type,
                "lesson_group_name": lesson.group_name,
                "lesson_date": _format_run_date(schedule["lesson_date"]),
                "lesson_code": lesson.lesson_code or "",
                "lesson_count": lesson.lesson_count or "",
                "absents": clean_absents,
                "makeup_time": values["makeup_time"],
                "next_lesson_date": values["next_lesson_date"],
                "next_lesson_day": values["next_lesson_day"],
                "next_lesson_time": values["next_lesson_time"],
                "send_date": values["send_date"],
                "send_time": values["send_time"],
                "telegram_plan_after": plan_after_datetime.isoformat(timespec="minutes"),
                "creation_delay_minutes": _absent_followup_delay_minutes(settings),
                "schedule_mode": getattr(settings, "absent_followup_schedule_mode", None) or "after_report",
            },
            ensure_ascii=False,
        ),
    )
    db.add(auto_msg)
    db.flush()
    return auto_msg


def _record_report_run(
    db: Session,
    lesson: ParentReportLesson,
    lesson_date: date,
    status: str,
    message: str | None,
    error: str | None,
    telegram_group_id: int | None,
    absents: str | None,
    is_auto: bool,
    is_test: bool,
):
    run = ParentReportRun(
        lesson_group_name=lesson.group_name,
        lesson_date=_format_run_date(lesson_date),
        lesson_id=lesson.id,
        telegram_group_id=telegram_group_id,
        status=status,
        message=message,
        error=error,
        absents=absents or "",
        is_auto=1 if is_auto else 0,
        is_test=1 if is_test else 0,
        created_at=_now_iso(),
    )
    db.add(run)
    db.flush()
    return run


def _mark_lesson_reported(db: Session, lesson: ParentReportLesson, lesson_date: date, absents: str | None):
    lesson.last_report_date = _format_display_date(lesson_date)
    lesson.absents = (absents or "").strip()
    lesson.postponed_start_at = None
    lesson.postponed_from_date = None
    lesson.postponed_created_at = None
    if lesson.lesson_count and str(lesson.lesson_count).strip().isdigit():
        lesson.lesson_count = str(int(str(lesson.lesson_count).strip()) + 1)


async def _send_lesson_report(
    db: Session,
    lesson: ParentReportLesson,
    settings: ParentReportSettings,
    message: str | None,
    absents: str | None,
    is_auto: bool,
    is_test: bool,
) -> dict[str, Any]:
    schedule = _lesson_schedule_context(lesson, settings)
    if not schedule:
        _raise_report_http(
            400,
            "Не вдалося визначити дату/час уроку",
            action="Відправка звіту",
            lesson=lesson,
            log=not is_auto,
        )

    if not is_test and _lesson_date_is_closed(lesson, schedule["lesson_date"]):
        _raise_report_http(
            409,
            "Звіт для цього уроку вже відправлено",
            action="Відправка звіту",
            lesson=lesson,
            log=not is_auto,
        )

    telegram_group = _telegram_group_for_lesson(db, lesson)
    if not telegram_group:
        _raise_report_http(
            400,
            f"Для групи '{lesson.group_name}' не вибрано Telegram-групу",
            action="Відправка звіту",
            lesson=lesson,
            log=not is_auto,
        )

    if not pyrogram_manager.is_connected:
        _raise_report_http(
            400,
            "Telegram не підключено",
            action="Відправка звіту",
            lesson=lesson,
            log=not is_auto,
        )

    report_text = (message or "").strip()
    if not report_text:
        report_text = await _generate_ai_report(settings, lesson, absents, test=is_test, is_auto=is_auto)
    elif is_test and not report_text.startswith("ТЕСТ"):
        report_text = f"ТЕСТ\n{report_text}"

    result = await send_pyrogram_message(
        telegram_group.telegram_id,
        report_text,
        queue_label=f"\u0417\u0432\u0456\u0442 \u0431\u0430\u0442\u044c\u043a\u0430\u043c: {lesson.group_name}",
    )
    if not result.get("ok"):
        error = result.get("description") or "Не вдалося відправити звіт"
        _record_report_run(
            db,
            lesson,
            schedule["lesson_date"],
            "error",
            report_text,
            error,
            telegram_group.id,
            absents,
            is_auto,
            is_test,
        )
        db.commit()
        if not is_auto:
            _log_report_issue("ERROR", f"Відправка звіту для '{lesson.group_name}' у '{telegram_group.name}' не вдалася: {error}")
        raise HTTPException(status_code=502, detail=error)

    report_run = _record_report_run(
        db,
        lesson,
        schedule["lesson_date"],
        "success",
        report_text,
        None,
        telegram_group.id,
        absents,
        is_auto,
        is_test,
    )
    followup_auto_message = None
    if not is_test:
        try:
            followup_auto_message = _create_report_followup_auto_message(
                db,
                lesson,
                settings,
                telegram_group,
                schedule,
                report_run,
                absents or "",
            )
        except Exception as error:
            _log_report_issue(
                "WARNING",
                f"Не вдалося створити автоповідомлення після звіту '{lesson.group_name}': {error}",
            )
    if not is_test:
        _mark_lesson_reported(db, lesson, schedule["lesson_date"], absents)
        await _refresh_lesson_from_source(db, lesson)
    db.commit()
    db.refresh(lesson)

    if followup_auto_message:
        auto_messages.schedule_auto_message(followup_auto_message)
        if pyrogram_manager.is_connected:
            await auto_messages.schedule_created_auto_message_in_telegram(followup_auto_message.id)

    log_event(
        "INFO",
        "ParentsReport",
        f"Звіт для '{lesson.group_name}' відправлено у '{telegram_group.name}'"
        + (" (тест)" if is_test else ""),
    )

    return {
        "ok": True,
        "message": report_text,
        "telegram_group": {"id": telegram_group.id, "name": telegram_group.name},
        "lesson": _serialize_lesson(lesson, settings),
    }


def _collect_pending(
    db: Session,
    settings: ParentReportSettings,
    include_report_delay: bool = False,
    delay_minutes: int | None = None,
) -> list[dict[str, Any]]:
    now = datetime.now(KYIV_TZ)
    lessons = db.query(ParentReportLesson).order_by(
        ParentReportLesson.row_order,
        ParentReportLesson.day,
        ParentReportLesson.start_time,
    ).all()
    pending = []
    for lesson in lessons:
        item = _is_lesson_pending(
            db,
            lesson,
            settings,
            now,
            include_report_delay=include_report_delay,
            delay_minutes=delay_minutes,
        )
        if not item:
            continue
        telegram_group = _telegram_group_for_lesson(db, lesson)
        item["telegram_group_id"] = telegram_group.id if telegram_group else None
        item["telegram_group_name"] = telegram_group.name if telegram_group else ""
        item["mapping_ready"] = bool(telegram_group)
        pending.append(item)
    return pending


async def process_auto_reports():
    db = SessionLocal()
    try:
        settings = _get_or_create_settings(db)
        if not settings.auto_reports_enabled:
            return
        if not pyrogram_manager.is_connected:
            return
        if not settings.google_ai_api_key:
            log_event("WARNING", "ParentsReport", "Автозвіти увімкнені, але Google AI API key не заданий")
            return
        if settings.test_mode:
            log_event("WARNING", "ParentsReport", "Автозвіти не запускаються у тестовому режимі")
            return

        pending = _collect_pending(db, settings, include_report_delay=True)
        for item in pending:
            if item.get("is_postponed"):
                continue
            if not item.get("mapping_ready"):
                continue
            lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == item["id"]).first()
            if not lesson:
                continue

            # Автоматично перевіряємо актуальну тему та підтягуємо відсутніх з Logika перед автозвітом
            if getattr(lesson, "logika_schedule_id", None) or getattr(lesson, "source_sheet", None) == "Logika Backoffice":
                try:
                    from models import LogikaSettings
                    from routers.logika import get_authenticated_client, _extract_lesson_code
                    l_settings = db.query(LogikaSettings).first()
                    if l_settings and getattr(l_settings, "auto_fetch_absents", 1):
                        l_client = get_authenticated_client(l_settings, db)
                        today_date = datetime.now(KYIV_TZ).date()
                        fresh_sched = l_client.get_schedule(
                            page=0, size=50,
                            teacher_id=l_settings.teacher_id,
                            status="ACTIVE",
                            is_start_day_now=True,
                        )
                        today_item = None
                        for s_item in fresh_sched:
                            if s_item.get("group", {}).get("value") == lesson.group_name and s_item.get("start"):
                                try:
                                    s_date = datetime.fromisoformat(s_item["start"]).date()
                                    if s_date == today_date:
                                        today_item = s_item
                                        break
                                except Exception:
                                    pass
                        target_sched_id = lesson.logika_schedule_id
                        if today_item:
                            target_sched_id = today_item.get("id", target_sched_id)
                            new_title = (today_item.get("lesson", {}).get("value") or "").strip()
                            if new_title and new_title != lesson.lesson_title:
                                old_code = lesson.lesson_code
                                lesson.lesson_title = new_title
                                lesson.lesson_code = _extract_lesson_code(new_title)
                                lesson.logika_schedule_id = target_sched_id
                                log_event("INFO", "Logika", f"Зміна теми для '{lesson.group_name}': було {old_code} -> стало {lesson.lesson_code}")
                        if target_sched_id:
                            abs_list = l_client.get_absent_students(target_sched_id)
                            if abs_list:
                                lesson.absents = ", ".join(abs_list)
                            log_event("INFO", "Logika", f"Підтягнуто відсутніх для '{lesson.group_name}': {lesson.absents or 'усі присутні'}")
                        db.commit()
                except Exception as l_err:
                    log_event("WARNING", "Logika", f"Не вдалося оновити дані з Logika для '{lesson.group_name}': {l_err}")

            try:
                await _send_lesson_report(
                    db,
                    lesson,
                    settings,
                    message=None,
                    absents=lesson.absents or "",
                    is_auto=True,
                    is_test=False,
                )
            except HTTPException as error:
                log_event("WARNING", "ParentsReport", f"Автозвіт для '{lesson.group_name}' не відправлено: {error.detail}")
            except Exception as error:
                log_event("ERROR", "ParentsReport", f"Автозвіт для '{lesson.group_name}' не відправлено: {error}")
    finally:
        db.close()


def _has_report_notification(db: Session, lesson: ParentReportLesson, lesson_date: date) -> bool:
    run_date = _format_run_date(lesson_date)
    existing = db.query(ParentReportNotification).filter(
        ParentReportNotification.lesson_group_name == lesson.group_name,
        ParentReportNotification.lesson_date == run_date,
    ).first()
    return existing is not None


def _record_report_notification(db: Session, lesson: ParentReportLesson, lesson_date: date):
    db.add(ParentReportNotification(
        lesson_id=lesson.id,
        lesson_group_name=lesson.group_name,
        lesson_date=_format_run_date(lesson_date),
        notified_at=_now_iso(),
    ))


async def process_report_system_notifications():
    db = SessionLocal()
    try:
        settings = _get_or_create_settings(db)
        if not getattr(settings, "report_notifications_enabled", 1):
            return

        notification_delay = getattr(settings, "report_notification_delay_minutes", 0) or 0
        pending = _collect_pending(db, settings, delay_minutes=notification_delay)
        due_lessons: list[tuple[ParentReportLesson, date, str]] = []

        for item in pending:
            lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == item["id"]).first()
            if not lesson:
                continue
            context = _lesson_schedule_context(lesson, settings, delay_minutes=notification_delay)
            if not context or _has_report_notification(db, lesson, context["lesson_date"]):
                continue
            due_lessons.append((lesson, context["lesson_date"], item.get("end_time") or ""))

        if not due_lessons:
            return

        if len(due_lessons) == 1:
            lesson, _lesson_date, end_time = due_lessons[0]
            title = "Потрібно відправити звіт"
            message = f"{lesson.group_name}: урок завершився о {end_time or '-'}, звіт готовий до відправки."
        else:
            group_names = ", ".join(lesson.group_name for lesson, _lesson_date, _end_time in due_lessons[:3])
            if len(due_lessons) > 3:
                group_names += f" та ще {len(due_lessons) - 3}"
            title = "Є уроки, які потребують звіт"
            message = f"{len(due_lessons)} уроків готові до звіту: {group_names}."

        if show_system_notification(title, message):
            for lesson, lesson_date, _end_time in due_lessons:
                _record_report_notification(db, lesson, lesson_date)
            db.commit()
            log_event("INFO", "ParentsReport", f"Показано системне сповіщення про {len(due_lessons)} звіт(и)")
    except Exception as error:
        log_event("WARNING", "ParentsReport", f"Не вдалося перевірити системні сповіщення звітів: {error}")
    finally:
        db.close()


def init_scheduler(scheduler):
    if scheduler.get_job(AUTO_REPORT_JOB_ID):
        scheduler.remove_job(AUTO_REPORT_JOB_ID)
    if scheduler.get_job(REPORT_NOTIFICATION_JOB_ID):
        scheduler.remove_job(REPORT_NOTIFICATION_JOB_ID)
    scheduler.add_job(
        process_auto_reports,
        "interval",
        seconds=AUTO_REPORT_INTERVAL_SECONDS,
        id=AUTO_REPORT_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_report_system_notifications,
        "interval",
        seconds=AUTO_REPORT_INTERVAL_SECONDS,
        id=REPORT_NOTIFICATION_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


@router.get("/settings")
def get_report_settings(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    db.commit()
    db.refresh(settings)
    return _settings_response(settings)


@router.get("/settings/api-key")
def get_report_api_key(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    return {"google_ai_api_key": settings.google_ai_api_key or ""}


@router.put("/settings")
def update_report_settings(payload: ReportSettingsUpdate, db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)

    if payload.google_ai_api_key is not None:
        key = payload.google_ai_api_key.strip()
        if key and set(key) <= {"•", "*"}:
            pass
        else:
            settings.google_ai_api_key = key or None
    if payload.google_ai_model is not None:
        settings.google_ai_model = payload.google_ai_model.strip() or DEFAULT_MODEL
    if payload.prompt_template is not None:
        settings.prompt_template = payload.prompt_template.strip() or DEFAULT_PROMPT_TEMPLATE
    if payload.auto_reports_enabled is not None:
        settings.auto_reports_enabled = 1 if payload.auto_reports_enabled else 0
    if payload.report_delay_minutes is not None:
        settings.report_delay_minutes = max(0, min(240, int(payload.report_delay_minutes)))
    if payload.report_notifications_enabled is not None:
        settings.report_notifications_enabled = 1 if payload.report_notifications_enabled else 0
    if payload.report_notification_delay_minutes is not None:
        settings.report_notification_delay_minutes = max(0, min(240, int(payload.report_notification_delay_minutes)))
    if payload.absent_followup_enabled is not None:
        settings.absent_followup_enabled = 1 if payload.absent_followup_enabled else 0
    if payload.absent_followup_schedule_mode is not None:
        mode = payload.absent_followup_schedule_mode.strip()
        settings.absent_followup_schedule_mode = mode if mode in {"after_report", "before_next_lesson"} else "after_report"
    if payload.absent_followup_delay_minutes is not None:
        settings.absent_followup_delay_minutes = max(0, min(10080, int(payload.absent_followup_delay_minutes)))
    if payload.absent_followup_before_lesson_time is not None:
        settings.absent_followup_before_lesson_time = _normalize_time(
            payload.absent_followup_before_lesson_time
            or DEFAULT_ABSENT_FOLLOWUP_BEFORE_LESSON_TIME
        )
    if payload.absent_followup_template is not None:
        settings.absent_followup_template = payload.absent_followup_template.strip() or DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
    if payload.no_absents_followup_template is not None:
        settings.no_absents_followup_template = (
            payload.no_absents_followup_template.strip()
            or DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE
        )
    if payload.default_duration_minutes is not None:
        settings.default_duration_minutes = max(30, min(360, int(payload.default_duration_minutes)))
    if payload.test_mode is not None:
        settings.test_mode = 1 if payload.test_mode else 0

    settings.updated_at = _now_iso()
    db.commit()
    db.refresh(settings)
    return _settings_response(settings)


@router.post("/settings/reset-prompt")
def reset_report_prompt_settings(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    settings.prompt_template = DEFAULT_PROMPT_TEMPLATE
    settings.updated_at = _now_iso()
    db.commit()
    db.refresh(settings)
    return _settings_response(settings)


@router.post("/import")
async def import_google_sheet(payload: ImportRequest = Body(...), db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    spreadsheet_url = (payload.spreadsheet_url or "").strip()
    if not spreadsheet_url:
        _raise_report_http(400, "Вкажіть посилання на Google Таблицю з локальним розкладом", action="Імпорт розкладу")

    try:
        path = await _download_sheet_xlsx(spreadsheet_url)
        try:
            sheets = _parse_xlsx(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        result = _apply_schedule_workbook_to_db(db, sheets, settings)
        log_event(
            "INFO",
            "ParentsReport",
            f"Імпортовано локальний розклад з Google Таблиці: {result['imported_lessons']} уроків",
        )
        return result
    except HTTPException as error:
        _log_report_issue(_http_level(error.status_code), f"Імпорт розкладу з Google Таблиці не вдався: {error.detail}")
        raise
    except Exception as error:
        _log_report_issue("ERROR", f"Імпорт розкладу з Google Таблиці не вдався: {error}")
        raise


@router.post("/sync-source")
async def sync_builtin_report_source(db: Session = Depends(get_db)):
    try:
        settings = _get_or_create_settings(db)
        path = await _download_source_xlsx()
        try:
            sheets = _parse_xlsx(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        result = _apply_source_courses_to_db(db, sheets, settings)
        log_event(
            "INFO",
            "ParentsReport",
            "Базу звітів оновлено",
        )
        return {"ok": True, "message": "Базу звітів оновлено"}
    except HTTPException as error:
        _log_report_issue(_http_level(error.status_code), f"Оновлення бази звітів не вдалося: {error.detail}")
        raise
    except Exception as error:
        _log_report_issue("ERROR", f"Оновлення бази звітів не вдалося: {error}")
        raise


@router.post("/import-file")
async def import_xlsx_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".xlsx"):
        _raise_report_http(400, "Потрібен файл .xlsx", action="Імпорт розкладу")

    try:
        settings = _get_or_create_settings(db)
        target = tempfile.NamedTemporaryFile(prefix="school_manager_report_upload_", suffix=".xlsx", delete=False)
        target_path = target.name
        try:
            content = await file.read()
            target.write(content)
            target.close()
            sheets = _parse_xlsx(target_path)
        finally:
            try:
                target.close()
            except Exception:
                pass
            try:
                os.remove(target_path)
            except OSError:
                pass

        result = _apply_schedule_workbook_to_db(db, sheets, settings)
        log_event(
            "INFO",
            "ParentsReport",
            f"Імпортовано локальний розклад з файлу {file.filename}: {result['imported_lessons']} уроків",
        )
        return result
    except HTTPException as error:
        _log_report_issue(_http_level(error.status_code), f"Імпорт розкладу з файлу не вдався: {error.detail}")
        raise
    except Exception as error:
        _log_report_issue("ERROR", f"Імпорт розкладу з файлу не вдався: {error}")
        raise


def _xml_escape(value: Any) -> str:
    text_value = str(value if value is not None else "")
    return (
        text_value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _col_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _sheet_xml(rows: list[list[Any]]) -> str:
    xml_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row):
            if value is None:
                value = ""
            ref = f"{_col_name(col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_escape(value)}</t></is></c>'
            )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        '</worksheet>'
    )


def _safe_sheet_name(name: str, used: set[str]) -> str:
    safe = re.sub(r"[:\\/?*\[\]]", "_", str(name or "Sheet")).strip() or "Sheet"
    safe = safe[:31]
    base = safe
    suffix = 2
    while safe.casefold() in used:
        extra = f" {suffix}"
        safe = (base[: 31 - len(extra)] + extra).strip()
        suffix += 1
    used.add(safe.casefold())
    return safe


def _workbook_to_xlsx_bytes(sheets: list[tuple[str, list[list[Any]]]]) -> bytes:
    used_names: set[str] = set()
    safe_sheets = [(_safe_sheet_name(title, used_names), rows) for title, rows in sheets]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        sheet_overrides = "\n".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(safe_sheets) + 1)
        )
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f"{sheet_overrides}"
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        sheet_nodes = "".join(
            f'<sheet name="{_xml_escape(title)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (title, _rows) in enumerate(safe_sheets, start=1)
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_nodes}</sheets>"
            "</workbook>",
        )
        rel_nodes = "".join(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(safe_sheets) + 1)
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rel_nodes}"
            "</Relationships>",
        )
        for index, (_title, rows) in enumerate(safe_sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))
    return output.getvalue()


@router.get("/export")
def export_workbook(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lessons = db.query(ParentReportLesson).order_by(ParentReportLesson.row_order, ParentReportLesson.id).all()

    schedule_rows = [SCHEDULE_HEADERS]
    for lesson in lessons:
        serialized = _serialize_lesson(lesson, settings)
        schedule_rows.append([
            serialized["group_name"],
            serialized["day"],
            serialized["start_time"],
            serialized["course"],
            serialized["lesson_code"],
            serialized["lesson_count"],
            serialized["last_report_date"],
            serialized["absents"],
            serialized["lesson_title"],
            serialized["duration_minutes"],
        ])

    sheets: list[tuple[str, list[list[Any]]]] = [
        ("Розклад", schedule_rows),
    ]

    payload = _workbook_to_xlsx_bytes(sheets)
    filename = f"school_manager_schedule_{datetime.now(KYIV_TZ).strftime('%Y%m%d_%H%M')}.xlsx"
    log_event("INFO", "ParentsReport", f"Експортовано локальний розклад: {len(lessons)} рядків")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/workbook")
def get_workbook(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lessons = db.query(ParentReportLesson).order_by(ParentReportLesson.row_order, ParentReportLesson.id).all()
    courses = db.query(ParentReportCourse).order_by(ParentReportCourse.row_order, ParentReportCourse.id).all()
    return {
        "schedule": [_serialize_lesson(lesson, settings) for lesson in lessons],
        "courses": [_serialize_course(course, include_lessons=False) for course in courses],
        "sheet_names": ["Розклад груп"],
    }


@router.get("/lessons")
def get_lessons(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lessons = db.query(ParentReportLesson).order_by(ParentReportLesson.row_order, ParentReportLesson.id).all()
    return [_serialize_lesson(lesson, settings) for lesson in lessons]


@router.post("/schedule")
def create_schedule_row(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    max_order = db.query(func.max(ParentReportLesson.row_order)).scalar() or 0
    lesson = ParentReportLesson(
        source_sheet="Розклад груп",
        source_row=max_order + 1,
        row_order=max_order + 1,
        group_name="Нова група",
        day="ПН",
        start_time="18:00",
        course="",
        lesson_code="",
        lesson_count="1",
        lesson_title="",
        lesson_topic_detail="",
        lesson_report_text="",
        topic="",
        duration_minutes=settings.default_duration_minutes or DEFAULT_DURATION_MINUTES,
        last_report_date="",
        absents="",
        imported_at=_now_iso(),
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return _serialize_lesson(lesson, settings)


@router.patch("/schedule/{lesson_id}")
async def update_schedule_row(lesson_id: int, payload: ScheduleUpdate, db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не знайдено")

    data = payload.model_dump(exclude_unset=True)
    previous_group_name = lesson.group_name
    if "telegram_group_id" in data:
        group_id = data.pop("telegram_group_id")
        if group_id:
            group = db.query(Group).filter(Group.id == group_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="Telegram-групу не знайдено")
            lesson.telegram_group_id = group.id
            lesson.group_name = group.name
        else:
            lesson.telegram_group_id = None

    for key, value in data.items():
        if key == "day" and value is not None:
            value = _normalize_day(value)
        if key == "start_time" and value is not None:
            value = _normalize_time(value)
        if key == "duration_minutes" and value is not None:
            value = max(1, min(600, int(value)))
        if hasattr(lesson, key):
            setattr(lesson, key, value)

    if "group_name" in data and not lesson.telegram_group_id:
        group = next((item for item in db.query(Group).all() if _normalize_name(item.name) == _normalize_name(lesson.group_name)), None)
        if group:
            lesson.telegram_group_id = group.id

    if "lesson_count" in data:
        await _refresh_lesson_from_source(db, lesson)
    elif "lesson_code" in data:
        await _refresh_lesson_from_source_by_code(db, lesson)
    elif "course" in data:
        await _refresh_lesson_from_source(db, lesson)

    if "last_report_date" in data:
        db.query(ParentReportNotification).filter(
            ParentReportNotification.lesson_id == lesson.id
        ).delete(synchronize_session=False)
        db.query(ParentReportNotification).filter(
            ParentReportNotification.lesson_group_name.in_([previous_group_name, lesson.group_name])
        ).delete(synchronize_session=False)

    db.commit()
    db.refresh(lesson)
    return _serialize_lesson(lesson, settings)


@router.post("/schedule/{lesson_id}/postpone")
def postpone_schedule_row(lesson_id: int, payload: PostponeLessonRequest, db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не знайдено")

    start_dt = _parse_postpone_start(payload.date, payload.time)
    if start_dt < datetime.now(KYIV_TZ):
        raise HTTPException(status_code=400, detail="Дата і час перенесеного уроку не можуть бути в минулому")

    original_context = _lesson_schedule_context(lesson, settings, use_postponed=False)
    lesson.postponed_start_at = start_dt.isoformat()
    lesson.postponed_from_date = _format_run_date(original_context["lesson_date"]) if original_context else ""
    lesson.postponed_created_at = _now_iso()

    db.query(ParentReportNotification).filter(
        ParentReportNotification.lesson_id == lesson.id
    ).delete(synchronize_session=False)
    db.query(ParentReportNotification).filter(
        ParentReportNotification.lesson_group_name == lesson.group_name
    ).delete(synchronize_session=False)

    db.commit()
    db.refresh(lesson)
    log_event("INFO", "ParentsReport", f"Урок для '{lesson.group_name}' перенесено на {start_dt.strftime('%d.%m.%Y %H:%M')}")
    return _serialize_lesson(lesson, settings)


@router.delete("/schedule/{lesson_id}/postpone")
def cancel_schedule_postpone(lesson_id: int, db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не знайдено")

    lesson.postponed_start_at = None
    lesson.postponed_from_date = None
    lesson.postponed_created_at = None
    db.query(ParentReportNotification).filter(
        ParentReportNotification.lesson_id == lesson.id
    ).delete(synchronize_session=False)
    db.commit()
    db.refresh(lesson)
    log_event("INFO", "ParentsReport", f"Перенесення уроку для '{lesson.group_name}' скасовано")
    return _serialize_lesson(lesson, settings)


@router.delete("/schedule/{lesson_id}")
def delete_schedule_row(lesson_id: int, db: Session = Depends(get_db)):
    lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не знайдено")
    db.delete(lesson)
    db.commit()
    return {"ok": True}


@router.get("/courses")
def get_courses(db: Session = Depends(get_db)):
    courses = db.query(ParentReportCourse).order_by(ParentReportCourse.row_order, ParentReportCourse.id).all()
    return [_serialize_course(course, include_lessons=False) for course in courses]


@router.post("/courses")
def create_course(payload: CourseCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Назва курсу обов'язкова")
    if db.query(ParentReportCourse).filter(ParentReportCourse.name == name).first():
        raise HTTPException(status_code=409, detail="Такий курс уже існує")
    max_order = db.query(func.max(ParentReportCourse.row_order)).scalar() or 0
    course = ParentReportCourse(name=name, source_sheet=name, row_order=max_order + 1, updated_at=_now_iso())
    db.add(course)
    db.commit()
    db.refresh(course)
    return _serialize_course(course, include_lessons=True)


@router.patch("/courses/{course_id}")
def update_course(course_id: int, payload: CourseUpdate, db: Session = Depends(get_db)):
    course = db.query(ParentReportCourse).filter(ParentReportCourse.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не знайдено")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Назва курсу обов'язкова")
        duplicate = db.query(ParentReportCourse).filter(
            ParentReportCourse.name == name,
            ParentReportCourse.id != course.id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Такий курс уже існує")
        old_name = course.name
        course.name = name
        course.source_sheet = name
        for item in course.lessons:
            item.course_name = name
            item.source_sheet = name
        db.query(ParentReportLesson).filter(ParentReportLesson.course == old_name).update({"course": name})
    if payload.row_order is not None:
        course.row_order = int(payload.row_order)
    course.updated_at = _now_iso()
    db.commit()
    db.refresh(course)
    return _serialize_course(course, include_lessons=True)


@router.delete("/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = db.query(ParentReportCourse).filter(ParentReportCourse.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не знайдено")
    db.delete(course)
    db.commit()
    return {"ok": True}


@router.post("/courses/{course_id}/lessons")
def create_course_lesson(course_id: int, payload: CourseLessonCreate, db: Session = Depends(get_db)):
    course = db.query(ParentReportCourse).filter(ParentReportCourse.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Курс не знайдено")
    max_order = db.query(func.max(ParentReportCourseLesson.row_order)).filter(
        ParentReportCourseLesson.course_id == course.id
    ).scalar() or 0
    lesson_count = payload.lesson_count or max_order + 1
    item = ParentReportCourseLesson(
        course_id=course.id,
        course_name=course.name,
        lesson_count=lesson_count,
        lesson_code=payload.lesson_code or "",
        module=payload.module or "",
        lesson_title=payload.lesson_title or "",
        lesson_topic_detail=payload.lesson_topic_detail or "",
        lesson_report_text=payload.lesson_report_text or payload.lesson_topic_detail or "",
        notes=payload.notes or "",
        source_sheet=course.name,
        source_row=lesson_count + 1,
        row_order=max_order + 1,
        raw_data=json.dumps(payload.model_dump(), ensure_ascii=False),
    )
    db.add(item)
    course.updated_at = _now_iso()
    db.commit()
    db.refresh(item)
    return _serialize_course_lesson(item)


@router.patch("/course-lessons/{lesson_id}")
def update_course_lesson(lesson_id: int, payload: CourseLessonUpdate, db: Session = Depends(get_db)):
    item = db.query(ParentReportCourseLesson).filter(ParentReportCourseLesson.id == lesson_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Урок курсу не знайдено")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in {"lesson_count", "row_order"} and value is not None:
            value = int(value)
        setattr(item, key, value)
    if "lesson_count" in data and item.lesson_count:
        item.source_row = item.lesson_count + 1
    item.course.updated_at = _now_iso()

    affected = db.query(ParentReportLesson).filter(
        ParentReportLesson.course == item.course_name,
        ParentReportLesson.lesson_count == str(item.lesson_count),
    ).all()
    for lesson in affected:
        _refresh_lesson_from_course(db, lesson)

    db.commit()
    db.refresh(item)
    return _serialize_course_lesson(item)


@router.delete("/course-lessons/{lesson_id}")
def delete_course_lesson(lesson_id: int, db: Session = Depends(get_db)):
    item = db.query(ParentReportCourseLesson).filter(ParentReportCourseLesson.id == lesson_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Урок курсу не знайдено")
    course = item.course
    db.delete(item)
    course.updated_at = _now_iso()
    db.commit()
    return {"ok": True}


@router.get("/pending")
def get_pending_reports(db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    return {"pending_lessons": _collect_pending(db, settings)}


@router.get("/mappings")
def get_mappings(db: Session = Depends(get_db)):
    lessons = db.query(ParentReportLesson).order_by(ParentReportLesson.group_name).all()
    result = []
    seen = set()
    for lesson in lessons:
        normalized = _normalize_name(lesson.group_name)
        if normalized in seen:
            continue
        seen.add(normalized)
        group = _telegram_group_for_lesson(db, lesson)
        result.append({
            "id": lesson.id,
            "lesson_group_name": lesson.group_name,
            "telegram_group_id": group.id if group else None,
            "telegram_group_name": group.name if group else "",
        })
    return result


@router.put("/mappings")
def update_mapping(payload: MappingUpdate, db: Session = Depends(get_db)):
    group_name = payload.lesson_group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Назва групи обов'язкова")

    telegram_group = None
    if payload.telegram_group_id is not None:
        telegram_group = db.query(Group).filter(Group.id == payload.telegram_group_id).first()
        if not telegram_group:
            raise HTTPException(status_code=404, detail="Telegram-групу не знайдено")

    item = db.query(ParentReportGroupMap).filter(ParentReportGroupMap.lesson_group_name == group_name).first()
    if not item:
        item = ParentReportGroupMap(lesson_group_name=group_name)
        db.add(item)
    item.telegram_group_id = payload.telegram_group_id
    item.updated_at = _now_iso()

    for lesson in db.query(ParentReportLesson).filter(ParentReportLesson.group_name == group_name).all():
        lesson.telegram_group_id = payload.telegram_group_id

    db.commit()
    db.refresh(item)

    return {
        "id": item.id,
        "lesson_group_name": item.lesson_group_name,
        "telegram_group_id": item.telegram_group_id,
        "telegram_group_name": telegram_group.name if telegram_group else "",
    }


@router.post("/send")
async def send_report(payload: SendReportRequest, db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == payload.lesson_id).first()
    if not lesson:
        _raise_report_http(404, "Урок не знайдено", action="Відправка звіту")

    absents = (payload.absents or "").strip()
    test = bool(settings.test_mode) if payload.test is None else bool(payload.test)
    return await _send_lesson_report(
        db,
        lesson,
        settings,
        message=None,
        absents=absents,
        is_auto=False,
        is_test=test,
    )


@router.get("/runs")
def get_report_runs(limit: int = 100, db: Session = Depends(get_db)):
    runs = db.query(ParentReportRun).order_by(ParentReportRun.id.desc()).limit(max(1, min(500, limit))).all()
    telegram_groups = {
        group.id: group.name
        for group in db.query(Group).filter(Group.id.in_([run.telegram_group_id for run in runs if run.telegram_group_id])).all()
    }
    return [
        {
            "id": run.id,
            "lesson_group_name": run.lesson_group_name,
            "lesson_date": run.lesson_date,
            "telegram_group_id": run.telegram_group_id,
            "telegram_group_name": telegram_groups.get(run.telegram_group_id, ""),
            "status": run.status,
            "message": run.message or "",
            "error": run.error or "",
            "absents": run.absents or "",
            "is_auto": bool(run.is_auto),
            "is_test": bool(run.is_test),
            "created_at": run.created_at,
        }
        for run in runs
    ]


@router.post("/auto/run-now")
async def run_auto_reports_now():
    await process_auto_reports()
    return {"ok": True}
