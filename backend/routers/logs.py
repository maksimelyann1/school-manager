from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import AppLog
from schemas import AppLogResponse

router = APIRouter(prefix="/logs", tags=["Журнал подій"])


@router.get("", response_model=List[AppLogResponse])
@router.get("/", response_model=List[AppLogResponse], include_in_schema=False)
def get_logs(limit: int = 100, db: Session = Depends(get_db)):
    """Отримати останні логи"""
    # Сортуємо за спаданням ID (найновіші перші)
    logs = db.query(AppLog).order_by(AppLog.id.desc()).limit(limit).all()
    return logs


@router.delete("")
@router.delete("/", include_in_schema=False)
def clear_logs(db: Session = Depends(get_db)):
    """Очистити всі логи"""
    db.query(AppLog).delete()
    db.commit()
    return {"message": "Журнал очищено"}
