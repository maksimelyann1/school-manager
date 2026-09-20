from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from database import get_db
from models import Group, AutoMessage, LogikaSettings, ParentReportLesson
from schemas import DashboardStatsResponse
from routers.parents_report import (
    _collect_pending,
    _get_or_create_settings,
    _telegram_group_for_lesson,
    KYIV_TZ,
    WEEKDAY_MAP,
    _normalize_day,
    _normalize_time,
)
from datetime import date, time, timedelta
from pyrogram_client import pyrogram_manager
from routers.auto_messages import _next_target_datetime

router = APIRouter(prefix="/dashboard", tags=["Дашборд"])

def get_time_left_str(target_dt: datetime) -> str:
    now = datetime.now()
    diff = target_dt - now
    days = diff.days
    seconds = diff.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if days == 0:
        if hours == 0:
            return f"через {minutes} хв"
        return f"сьогодні о {target_dt.strftime('%H:%M')} (через {hours} год)"
    elif days == 1:
        return f"завтра о {target_dt.strftime('%H:%M')}"
    else:
        return f"через {days} дн. о {target_dt.strftime('%H:%M')}"

@router.get("/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Отримати статистику для дашборду"""
    
    # 1. Загальна кількість груп
    total_groups = db.query(Group).count()
    
    # 2. Статус підключення
    is_connected = pyrogram_manager.is_connected
    
    # 3. Аналіз розкладу повідомлень
    auto_msgs = db.query(AutoMessage).filter(AutoMessage.is_active == 1).all()
    
    now = datetime.now()
    upcoming_list = []
    today_count = 0
    
    for am in auto_msgs:
        group = db.query(Group).filter(Group.id == am.group_id).first()
        if not group: continue
        
        target_datetime = _next_target_datetime(am)
        if not target_datetime:
            continue
        
        # Якщо час сьогодні вже минув, воно заплановане на наступний тиждень
        # Рахуємо скільки повідомлень на "сьогодні" (від сьогоднішньої опівночі до завтрашньої)
        # Оскільки target_datetime завжди в майбутньому (або зараз), то якщо days_ahead == 0 і воно не перенеслось на тиждень,
        # це означає, що воно сьогодні в майбутньому
        if target_datetime.date() == now.date():
            today_count += 1
            
        upcoming_list.append({
            "id": am.id,
            "group_name": group.name,
            "message": am.message,
            "target_datetime": target_datetime,
            "time_left": get_time_left_str(target_datetime)
        })
        
    # Сортуємо за найближчим часом відправки
    upcoming_list.sort(key=lambda x: x["target_datetime"])
    
    # Беремо топ 10 для відмальовки
    top_upcoming = upcoming_list[:10]
    
    # Конвертуємо datetime в ISO рядок для схеми
    result_upcoming = []
    for item in top_upcoming:
        item_copy = item.copy()
        item_copy["target_datetime"] = item["target_datetime"].isoformat()
        result_upcoming.append(item_copy)
        
    # 4. Інформація про Logika та Звіти
    l_settings = db.query(LogikaSettings).first()
    logika_connected = bool(l_settings and l_settings.login and l_settings.password and l_settings.access_token)
    logika_teacher_name = l_settings.teacher_name if l_settings else None
    logika_login = l_settings.login if l_settings else None

    # Звіти батькам
    p_settings = _get_or_create_settings(db)
    auto_reports_on = bool(p_settings.auto_reports_enabled)
    delay_min = p_settings.report_delay_minutes if p_settings.report_delay_minutes is not None else 10

    # Звіти, які потребують відправки
    raw_pending = _collect_pending(db, p_settings, include_report_delay=False)
    pending_items = []
    for item in raw_pending:
        pending_items.append({
            "id": item.get("id"),
            "group_name": item.get("group_name") or "",
            "telegram_group_name": item.get("telegram_group_name") or "",
            "mapping_ready": bool(item.get("mapping_ready")),
            "lesson_title": item.get("lesson_title") or "",
            "lesson_code": item.get("lesson_code") or "",
            "lesson_count": str(item.get("lesson_count") or ""),
            "lesson_date": str(item.get("lesson_date") or ""),
            "start_time": item.get("start_time") or "",
            "absents": item.get("absents") or "",
        })

    # Найближчий автозвіт
    next_auto = None
    if auto_reports_on:
        now_kyiv = datetime.now(KYIV_TZ)
        upcoming_reports = []
        all_lessons = db.query(ParentReportLesson).all()
        for l in all_lessons:
            day = _normalize_day(l.day or "")
            weekday = WEEKDAY_MAP.get(day)
            if weekday is None: continue
            start_time_str = _normalize_time(l.start_time or "")
            try:
                h, m = [int(x) for x in start_time_str.split(":", 1)]
            except Exception: continue
            duration = l.duration_minutes or 90
            days_ahead = (weekday - now_kyiv.weekday()) % 7
            cand_date = now_kyiv.date() + timedelta(days=days_ahead)
            cand_start = datetime.combine(cand_date, time(h, m), tzinfo=KYIV_TZ)
            cand_report_time = cand_start + timedelta(minutes=duration + delay_min)
            if cand_report_time <= now_kyiv:
                cand_report_time += timedelta(days=7)
                cand_start += timedelta(days=7)
            tg = _telegram_group_for_lesson(db, l)
            upcoming_reports.append({
                "lesson_id": l.id,
                "group_name": l.group_name or "",
                "telegram_group_name": tg.name if tg else "",
                "mapping_ready": bool(tg),
                "lesson_title": l.lesson_title or "",
                "lesson_code": l.lesson_code or "",
                "lesson_start": cand_start.isoformat(),
                "report_time": cand_report_time.isoformat(),
                "time_left": get_time_left_str(cand_report_time.replace(tzinfo=None)),
                "report_dt": cand_report_time,
            })
        if upcoming_reports:
            upcoming_reports.sort(key=lambda x: x["report_dt"])
            earliest = upcoming_reports[0]
            next_auto = {
                "lesson_id": earliest["lesson_id"],
                "group_name": earliest["group_name"],
                "telegram_group_name": earliest["telegram_group_name"],
                "mapping_ready": earliest["mapping_ready"],
                "lesson_title": earliest["lesson_title"],
                "lesson_code": earliest["lesson_code"],
                "lesson_start": earliest["lesson_start"],
                "report_time": earliest["report_time"],
                "time_left": earliest["time_left"],
            }

    reports_info = {
        "auto_reports_enabled": auto_reports_on,
        "report_delay_minutes": delay_min,
        "pending_count": len(pending_items),
        "pending_reports": pending_items,
        "next_auto_report": next_auto,
    }

    return {
        "is_connected": is_connected,
        "total_groups": total_groups,
        "today_scheduled_count": today_count,
        "upcoming_messages": result_upcoming,
        "logika_connected": logika_connected,
        "logika_teacher_name": logika_teacher_name,
        "logika_login": logika_login,
        "reports_info": reports_info,
    }
