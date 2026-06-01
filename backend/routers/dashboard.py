from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List

from database import get_db
from models import Group, AutoMessage
from schemas import DashboardStatsResponse
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
        
    return {
        "is_connected": is_connected,
        "total_groups": total_groups,
        "today_scheduled_count": today_count,
        "upcoming_messages": result_upcoming
    }
