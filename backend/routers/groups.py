# API для управління групами
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pyrogram.errors import FloodWait, RPCError
from pyrogram.enums import ChatType

from database import get_db
from models import Category, Group, BotSettings
from schemas import GroupBulkCategoryUpdate, GroupCreate, GroupResponse
from pyrogram_client import pyrogram_manager

router = APIRouter(prefix="/groups", tags=["Групи"])


async def sync_telegram_groups(db: Session) -> dict:
    """Синхронізувати групи з Telegram через Pyrogram."""
    if not pyrogram_manager.is_connected:
        raise HTTPException(status_code=400, detail="Telegram не підключено. Авторизуйтесь в Налаштуваннях.")

    client = pyrogram_manager.client
    added_count = 0

    try:
        # Отримуємо всі діалоги (групи, канали, чати)
        async for dialog in client.get_dialogs():
            chat = dialog.chat

            # Беремо тільки групи, супергрупи та канали
            if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
                continue

            chat_id = str(chat.id)
            title = chat.title or "Без назви"

            # Перевіряємо чи є вже така група в базі
            existing = db.query(Group).filter(Group.telegram_id == chat_id).first()
            if not existing:
                new_group = Group(name=title, telegram_id=chat_id)
                db.add(new_group)
                added_count += 1
                print(f"[Sync] ➕ Додано: {title} ({chat_id})")

        if added_count > 0:
            db.commit()

        print(f"[Sync] Синхронізація завершена: додано {added_count} нових груп/каналів")
        return {"message": "Синхронізація успішна", "added_count": added_count}

    except FloodWait as e:
        raise HTTPException(status_code=429, detail=f"Telegram просить зачекати {e.value}с")
    except RPCError as e:
        raise HTTPException(status_code=500, detail=f"Помилка Telegram: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка синхронізації: {str(e)}")


@router.post("/sync")
async def sync_groups(db: Session = Depends(get_db)):
    """Синхронізувати групи з Telegram через Pyrogram (знаходить всі групи/канали)"""
    return await sync_telegram_groups(db)


@router.get("/")
def get_all_groups(db: Session = Depends(get_db)):
    """Отримати всі групи з назвою категорії"""
    groups = db.query(Group).all()
    result = []
    for g in groups:
        group_dict = {
            "id": g.id,
            "name": g.name,
            "telegram_id": g.telegram_id,
            "lesson_time": g.lesson_time,
            "lesson_day": g.lesson_day,
            "category_id": g.category_id,
            "category_name": g.category.name if g.category else None
        }
        result.append(group_dict)
    return result


@router.patch("/bulk-category")
def update_groups_category(payload: GroupBulkCategoryUpdate, db: Session = Depends(get_db)):
    """Масово перенести групи/канали в категорію або прибрати категорію."""
    group_ids = list(dict.fromkeys(payload.group_ids or []))
    if not group_ids:
        raise HTTPException(status_code=400, detail="Виберіть хоча б одну групу")

    if payload.category_id is not None:
        category = db.query(Category).filter(Category.id == payload.category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Категорію не знайдено")

    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()
    found_ids = {group.id for group in groups}
    missing_ids = [group_id for group_id in group_ids if group_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Групи не знайдено: {missing_ids}")

    for group in groups:
        group.category_id = payload.category_id

    db.commit()
    return {
        "message": "Категорію груп оновлено",
        "updated_count": len(groups),
        "category_id": payload.category_id,
    }


@router.get("/{group_id}", response_model=GroupResponse)
def get_group(group_id: int, db: Session = Depends(get_db)):
    """Отримати групу за ID"""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Групу не знайдено")
    return group


@router.post("/", response_model=GroupResponse)
def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    """Створити нову групу"""
    db_group = Group(**group.model_dump())
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group


@router.put("/{group_id}", response_model=GroupResponse)
def update_group(group_id: int, group: GroupCreate, db: Session = Depends(get_db)):
    """Оновити групу"""
    db_group = db.query(Group).filter(Group.id == group_id).first()
    if not db_group:
        raise HTTPException(status_code=404, detail="Групу не знайдено")
    
    for key, value in group.model_dump().items():
        setattr(db_group, key, value)
    
    db.commit()
    db.refresh(db_group)
    return db_group


@router.delete("/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db)):
    """Видалити групу"""
    db_group = db.query(Group).filter(Group.id == group_id).first()
    if not db_group:
        raise HTTPException(status_code=404, detail="Групу не знайдено")
    
    db.delete(db_group)
    db.commit()
    return {"message": "Групу видалено"}
