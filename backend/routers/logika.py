import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from logger import log_event
from models import (
    Group,
    LogikaSettings,
    ParentReportCourse,
    ParentReportCourseLesson,
    ParentReportGroupMap,
    ParentReportLesson,
)
from logika_client import LogikaAuthError, LogikaClient

router = APIRouter(prefix="/logika", tags=["Logika Backoffice"])

UKR_DAYS = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Нд"}

def _extract_lesson_code(title: str) -> str:
    if not title:
        return ""
    # Шукаємо М1У2, M1U2, М1У2.1, тощо
    match = re.search(r'([МMмm]\d+[\.\s]*[УUуu]\d+(?:\.\d+)?)', title)
    if match:
        raw = match.group(1).upper().replace("M", "М").replace("U", "У").replace(" ", "")
        # Залишаємо вигляд М2У4 або М4У6.1
        return raw
    match = re.search(r'(?:Урок\s*|У)(\d+)', title, re.IGNORECASE)
    if match:
        return f"У{match.group(1)}"
    return ""



class LoginRequest(BaseModel):
    login: str
    password: str


class UpdateSettingsRequest(BaseModel):
    auto_sync_enabled: Optional[bool] = None
    auto_fetch_absents: Optional[bool] = None


def get_or_create_logika_settings(db: Session) -> LogikaSettings:
    settings = db.query(LogikaSettings).first()
    if not settings:
        settings = LogikaSettings(
            auto_sync_enabled=1,
            auto_fetch_absents=1,
            last_sync_count=0,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_authenticated_client(settings: LogikaSettings, db: Session) -> LogikaClient:
    if not settings.login or not settings.password:
        raise HTTPException(status_code=400, detail="Акаунт Logika не налаштований")

    client = LogikaClient(
        login=settings.login,
        password=settings.password,
        access_token=settings.access_token,
        refresh_token=settings.refresh_token,
        xsrf_token=settings.xsrf_token,
    )

    # Якщо токенів немає або вони застаріли, перевіряємо / оновлюємо
    if not settings.access_token:
        try:
            tokens = client.authenticate()
            settings.access_token = tokens.get("access_token")
            settings.refresh_token = tokens.get("refresh_token")
            settings.xsrf_token = tokens.get("xsrf_token")
            settings.token_expires_at = tokens.get("token_expires_at")
            settings.updated_at = datetime.now().isoformat()
            db.commit()
        except LogikaAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))

    return client


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    settings = get_or_create_logika_settings(db)
    return {
        "is_configured": bool(settings.login and settings.password),
        "login": settings.login or "",
        "teacher_name": settings.teacher_name or "",
        "teacher_id": settings.teacher_id,
        "auto_sync_enabled": bool(settings.auto_sync_enabled),
        "auto_fetch_absents": bool(settings.auto_fetch_absents),
        "last_sync_at": settings.last_sync_at,
        "last_sync_count": settings.last_sync_count,
        "last_error": settings.last_error,
        "has_active_token": bool(settings.access_token),
    }


@router.post("/login")
def login_logika(payload: LoginRequest, db: Session = Depends(get_db)):
    login_str = payload.login.strip()
    password_str = payload.password.strip()
    if not login_str or not password_str:
        raise HTTPException(status_code=400, detail="Введіть логін та пароль")

    settings = get_or_create_logika_settings(db)
    client = LogikaClient(login=login_str, password=password_str)

    try:
        tokens = client.authenticate()
    except LogikaAuthError as err:
        settings.last_error = str(err)
        db.commit()
        raise HTTPException(status_code=401, detail=str(err))
    except Exception as err:
        settings.last_error = str(err)
        db.commit()
        log_event("ERROR", "Logika", f"Помилка входу: {err}")
        raise HTTPException(status_code=500, detail=f"Помилка підключення до Logika: {err}")

    # Отримуємо ім'я викладача з розкладу
    teacher_name = None
    teacher_id = None
    try:
        sched = client.get_schedule(page=0, size=5)
        if sched and len(sched) > 0:
            t_info = sched[0].get("teacher") or {}
            teacher_name = t_info.get("value")
            teacher_id = t_info.get("key")
    except Exception as e:
        log_event("WARNING", "Logika", f"Не вдалося отримати ім'я викладача: {e}")

    settings.login = login_str
    settings.password = password_str
    settings.access_token = tokens.get("access_token")
    settings.refresh_token = tokens.get("refresh_token")
    settings.xsrf_token = tokens.get("xsrf_token")
    settings.token_expires_at = tokens.get("token_expires_at")
    if teacher_name:
        settings.teacher_name = teacher_name
    if teacher_id:
        settings.teacher_id = teacher_id
    settings.last_error = None
    settings.updated_at = datetime.now().isoformat()
    db.commit()
    db.refresh(settings)

    log_event("INFO", "Logika", f"Успішний вхід для викладача {teacher_name or login_str}")
    return {
        "success": True,
        "message": "Успішно авторизовано в Logika Backoffice",
        "teacher_name": settings.teacher_name or login_str,
        "teacher_id": settings.teacher_id,
    }


@router.post("/update-settings")
def update_settings(payload: UpdateSettingsRequest, db: Session = Depends(get_db)):
    settings = get_or_create_logika_settings(db)
    if payload.auto_sync_enabled is not None:
        settings.auto_sync_enabled = 1 if payload.auto_sync_enabled else 0
    if payload.auto_fetch_absents is not None:
        settings.auto_fetch_absents = 1 if payload.auto_fetch_absents else 0
    settings.updated_at = datetime.now().isoformat()
    db.commit()
    return {"success": True}


@router.post("/disconnect")
def disconnect_logika(db: Session = Depends(get_db)):
    settings = get_or_create_logika_settings(db)
    settings.login = None
    settings.password = None
    settings.access_token = None
    settings.refresh_token = None
    settings.xsrf_token = None
    settings.token_expires_at = None
    settings.teacher_name = None
    settings.teacher_id = None
    settings.last_error = None
    settings.updated_at = datetime.now().isoformat()
    db.commit()
    log_event("INFO", "Logika", "Акаунт Logika відключено")
    return {"success": True, "message": "Акаунт Logika відключено"}


@router.post("/sync-schedule")
def sync_schedule(db: Session = Depends(get_db)):
    settings = get_or_create_logika_settings(db)
    client = get_authenticated_client(settings, db)

    try:
        raw_lessons = client.get_schedule(
            page=0,
            size=100,
            teacher_id=settings.teacher_id,
            status="ACTIVE",
            active=True,
            is_start_day_now=True,
        )

        # Фільтруємо суворо за викладачем та статусом ACTIVE
        groups_map = {}
        for item in raw_lessons:
            if item.get("groupStatus") != "ACTIVE":
                continue
            if settings.teacher_id and item.get("teacher", {}).get("key") != settings.teacher_id:
                continue
            g_key = item.get("group", {}).get("key")
            g_name = (item.get("group", {}).get("value") or "").strip()
            if not g_key or not g_name:
                continue
            if g_key not in groups_map:
                groups_map[g_key] = g_name

        today = datetime.now().date()
        active_group_names = set()
        synced_count = 0
        updated_count = 0

        for g_key, g_name in groups_map.items():
            active_group_names.add(g_name)

            # Отримуємо повний розклад курсу цієї групи для точного підрахунку уроків
            all_group_lessons = []
            try:
                all_group_lessons = client.get_group_schedule(g_key)
            except Exception as err:
                log_event("WARNING", "Logika", f"Не вдалося отримати повний розклад групи {g_name}: {err}")

            if not all_group_lessons:
                continue

            # Сортуємо уроки групи хронологічно
            all_group_lessons.sort(key=lambda x: x.get("start") or "")
            finished_lessons = [l for l in all_group_lessons if l.get("lessonStatus") == "FINISH"]

            # Визначаємо поточний або найближчий урок
            target_lesson = None
            target_index = None
            for idx, it in enumerate(all_group_lessons, 1):
                if it.get("start"):
                    try:
                        d = datetime.fromisoformat(it["start"]).date()
                        if d == today:
                            target_lesson = it
                            target_index = idx
                            break
                    except Exception:
                        pass

            if not target_lesson:
                for idx, it in enumerate(all_group_lessons, 1):
                    if it.get("start"):
                        try:
                            d = datetime.fromisoformat(it["start"]).date()
                            if d >= today:
                                target_lesson = it
                                target_index = idx
                                break
                        except Exception:
                            pass

            if not target_lesson and all_group_lessons:
                target_lesson = all_group_lessons[-1]
                target_index = len(all_group_lessons)

            if not target_lesson:
                continue

            schedule_id = target_lesson.get("id")
            course_name = (target_lesson.get("course", {}).get("value") or "").strip()
            lesson_title = (target_lesson.get("lesson", {}).get("value") or "").strip()

            # Код уроку (напр. М2У4, М2У6, М2У1, М1У2)
            lesson_code_str = _extract_lesson_code(lesson_title)

            # Кількість проведених уроків (номер уроку або кількість завершених)
            lesson_count_str = str(target_index)

            start_iso = target_lesson.get("start")
            day_str = ""
            start_time_str = ""
            if start_iso:
                try:
                    dt = datetime.fromisoformat(start_iso)
                    day_str = UKR_DAYS.get(dt.weekday(), "")
                    start_time_str = dt.strftime("%H:%M")
                except Exception:
                    pass

            duration_sec = target_lesson.get("duration") or 5400
            duration_min = max(30, duration_sec // 60)

            # Отримуємо відсутніх для завершених або сьогоднішніх уроків
            absents_str = None
            attended = target_lesson.get("attendedAmount") or 0
            if target_lesson.get("lessonStatus") == "FINISH" or attended > 0:
                try:
                    absents_list = client.get_absent_students(schedule_id)
                    if absents_list:
                        absents_str = ", ".join(absents_list)
                except Exception as e:
                    log_event("WARNING", "Logika", f"Не вдалося отримати відсутніх для уроку {schedule_id}: {e}")

            # Залишаємо рівно 1 рядок на кожну групу у тижневому розкладі
            existing_rows = (
                db.query(ParentReportLesson)
                .filter(ParentReportLesson.group_name == g_name)
                .all()
            )

            if existing_rows:
                existing = existing_rows[0]
                for dup in existing_rows[1:]:
                    db.delete(dup)
                existing.logika_schedule_id = schedule_id
                existing.lesson_code = lesson_code_str
                existing.lesson_count = lesson_count_str
                if lesson_title:
                    existing.lesson_title = lesson_title
                if course_name:
                    existing.course = course_name
                if day_str:
                    existing.day = day_str
                if start_time_str:
                    existing.start_time = start_time_str
                if duration_min:
                    existing.duration_minutes = duration_min
                if absents_str is not None:
                    existing.absents = absents_str
                updated_count += 1
            else:
                new_lesson = ParentReportLesson(
                    source_sheet="Logika Backoffice",
                    group_name=g_name,
                    course=course_name,
                    lesson_title=lesson_title,
                    lesson_code=lesson_code_str,
                    lesson_count=lesson_count_str,
                    day=day_str,
                    start_time=start_time_str,
                    duration_minutes=duration_min,
                    logika_schedule_id=schedule_id,
                    absents=absents_str or "",
                    imported_at=datetime.now().isoformat(),
                )
                # Перевіряємо, чи є вже збережений мапінг для цієї назви
                legacy = db.query(ParentReportGroupMap).filter(ParentReportGroupMap.lesson_group_name == g_name).first()
                if legacy and legacy.telegram_group_id:
                    new_lesson.telegram_group_id = legacy.telegram_group_id

                db.add(new_lesson)
                synced_count += 1

        # Очищуємо старі рядки з source_sheet == "Logika Backoffice", чиї групи не є активними
        if active_group_names:
            inactive_rows = (
                db.query(ParentReportLesson)
                .filter(
                    ParentReportLesson.source_sheet == "Logika Backoffice",
                    ~ParentReportLesson.group_name.in_(active_group_names)
                )
                .all()
            )
            for old_row in inactive_rows:
                db.delete(old_row)

        total_active = len(groups_map)
        settings.last_sync_at = datetime.now().isoformat()
        settings.last_sync_count = total_active
        settings.last_error = None
        db.commit()

        log_event("INFO", "Logika", f"Синхронізовано {total_active} активних груп викладача (додано {synced_count}, оновлено {updated_count})")
        return {
            "success": True,
            "added": synced_count,
            "updated": updated_count,
            "total": total_active,
            "message": f"Синхронізовано {total_active} активних груп викладача",
        }
    except Exception as e:
        db.rollback()
        err_msg = str(e)
        log_event("ERROR", "Logika", f"Помилка синхронізації розкладу: {err_msg}")
        try:
            settings.last_error = err_msg
            db.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Помилка синхронізації розкладу: {err_msg}")

@router.post("/fetch-absents/{lesson_id}")
def fetch_absents_for_lesson(lesson_id: int, db: Session = Depends(get_db)):
    lesson = db.query(ParentReportLesson).filter(ParentReportLesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не знайдено")
    if not lesson.logika_schedule_id:
        raise HTTPException(status_code=400, detail="Урок не прив'язаний до розкладу Logika")

    settings = get_or_create_logika_settings(db)
    client = get_authenticated_client(settings, db)

    try:
        absents = client.get_absent_students(lesson.logika_schedule_id)
        absents_str = ", ".join(absents)
        lesson.absents = absents_str
        db.commit()
        return {
            "success": True,
            "absents": absents,
            "absents_text": absents_str,
        }
    except Exception as e:
        log_event("ERROR", "Logika", f"Помилка отримання відсутніх для уроку {lesson_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Помилка журналу Logika: {e}")
