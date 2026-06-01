# API для управління категоріями груп
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Category, Group
from schemas import CategoryCreate, CategoryResponse

router = APIRouter(prefix="/categories", tags=["Категорії"])


@router.get("/", response_model=List[CategoryResponse])
def get_all_categories(db: Session = Depends(get_db)):
    """Отримати всі категорії"""
    return db.query(Category).all()


@router.post("/", response_model=CategoryResponse)
def create_category(category: CategoryCreate, db: Session = Depends(get_db)):
    """Створити нову категорію"""
    name = category.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Введіть назву категорії")
    db_category = Category(name=name)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(category_id: int, category: CategoryCreate, db: Session = Depends(get_db)):
    """Оновити категорію"""
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(status_code=404, detail="Категорію не знайдено")

    name = category.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Введіть назву категорії")

    db_category.name = name
    db.commit()
    db.refresh(db_category)
    return db_category


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Видалити категорію (групи залишаються, але без категорії)"""
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(status_code=404, detail="Категорію не знайдено")
    
    # Знімаємо категорію з усіх груп
    db.query(Group).filter(Group.category_id == category_id).update(
        {Group.category_id: None}
    )
    
    db.delete(db_category)
    db.commit()
    return {"message": "Категорію видалено"}
