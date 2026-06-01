from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload
from typing import List
import json
import os

from database import get_db
from file_storage import (
    remove_file_quiet,
    save_stored_to_template,
    save_upload_to_template,
    template_file_path,
)
from models import Template, TemplateFile
from schemas import TemplateResponse

router = APIRouter(prefix="/templates", tags=["Шаблони"])


def _mark_file_exists(template: Template):
    template.files.sort(key=lambda item: (item.file_order or 0, item.id or 0))
    for file_item in template.files:
        file_item.exists = os.path.exists(template_file_path(file_item.stored_filename))
    return template


def _template_query(db: Session):
    return db.query(Template).options(selectinload(Template.files))


def _sanitize_sticker_items(items) -> list[dict]:
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="stickers має бути списком")

    stickers = []
    for item in items[:12]:
        if isinstance(item, str):
            file_id = item.strip()
            if file_id:
                stickers.append({"file_id": file_id})
            continue

        if not isinstance(item, dict):
            continue

        cleaned = {}
        for key in (
            "file_id",
            "document_id",
            "id",
            "emoji",
            "mime_type",
            "pack_short_name",
            "thumb_url",
            "animation_url",
            "preview_url",
            "file_name",
        ):
            value = item.get(key)
            if value is not None:
                cleaned[key] = value

        if item.get("is_animated") is not None:
            cleaned["is_animated"] = bool(item.get("is_animated"))
        if item.get("is_video") is not None:
            cleaned["is_video"] = bool(item.get("is_video"))

        if cleaned.get("file_id") or (cleaned.get("pack_short_name") and (cleaned.get("document_id") or cleaned.get("id"))):
            stickers.append(cleaned)

    return stickers


def _parse_stickers_payload(raw) -> list[dict]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return _sanitize_sticker_items(raw)
    try:
        items = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Неправильний формат stickers")
    return _sanitize_sticker_items(items)


def _stickers_from_template(template: Template) -> list[dict]:
    return _parse_stickers_payload(getattr(template, "stickers", "[]") or "[]")


def _serialize_template(template: Template):
    template = _mark_file_exists(template)
    return {
        "id": template.id,
        "name": template.name,
        "text": template.text or "",
        "files": template.files,
        "stickers": _stickers_from_template(template),
    }


async def _read_template_payload(request: Request):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        name = str(form.get("name") or "").strip()
        text = str(form.get("text") or "").strip()
        keep_raw = form.get("keep_file_ids") or "[]"
        try:
            keep_file_ids = [int(item) for item in json.loads(keep_raw)]
        except Exception:
            keep_file_ids = []
        stored_raw = form.get("stored_files") or "[]"
        try:
            stored_files = json.loads(stored_raw)
            if not isinstance(stored_files, list):
                raise ValueError("stored_files must be a list")
        except Exception:
            raise HTTPException(status_code=400, detail="Неправильний формат stored_files")
        stickers = _parse_stickers_payload(form.get("stickers") or "[]")

        files = []
        for item in form.getlist("files"):
            if getattr(item, "filename", None):
                files.append(item)

        return {
            "name": name,
            "text": text,
            "files": files,
            "stored_files": stored_files,
            "keep_file_ids": keep_file_ids,
            "stickers": stickers,
            "multipart": True,
        }

    data = await request.json()
    return {
        "name": str(data.get("name") or "").strip(),
        "text": str(data.get("text") or "").strip(),
        "files": [],
        "stored_files": [],
        "keep_file_ids": None,
        "stickers": _parse_stickers_payload(data.get("stickers") or []),
        "multipart": False,
    }


def _validate_template_payload(name: str, text: str, files_count: int, kept_count: int = 0, stickers_count: int = 0):
    if not name:
        raise HTTPException(status_code=400, detail="Введіть назву шаблону")
    if not text and files_count == 0 and kept_count == 0 and stickers_count == 0:
        raise HTTPException(status_code=400, detail="Додайте текст, файл або наліпку до шаблону")


async def _add_template_files(db: Session, template: Template, uploads, start_order: int = 0):
    for index, upload in enumerate(uploads):
        file_data = await save_upload_to_template(upload, start_order + index)
        db_file = TemplateFile(template_id=template.id, **file_data)
        db.add(db_file)


def _add_stored_template_files(db: Session, template: Template, stored_files, start_order: int = 0):
    for index, item in enumerate(stored_files):
        if not isinstance(item, dict):
            continue
        try:
            file_data = save_stored_to_template(item, start_order + index)
        except FileNotFoundError:
            filename = item.get("filename") or item.get("stored_filename") or "file"
            raise HTTPException(status_code=400, detail=f"Файл не знайдено: {filename}")
        except Exception as error:
            filename = item.get("filename") or item.get("stored_filename") or "file"
            raise HTTPException(status_code=400, detail=f"Не вдалося додати файл {filename}: {error}")
        db_file = TemplateFile(template_id=template.id, **file_data)
        db.add(db_file)


@router.get("/", response_model=List[TemplateResponse])
def get_all_templates(db: Session = Depends(get_db)):
    templates = _template_query(db).order_by(Template.name).all()
    return [_serialize_template(template) for template in templates]


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db)):
    template = _template_query(db).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не знайдено")
    return _serialize_template(template)


@router.post("/", response_model=TemplateResponse)
async def create_template(request: Request, db: Session = Depends(get_db)):
    payload = await _read_template_payload(request)
    new_files_count = len(payload["files"]) + len(payload["stored_files"])
    _validate_template_payload(payload["name"], payload["text"], new_files_count, stickers_count=len(payload["stickers"]))

    db_template = Template(
        name=payload["name"],
        text=payload["text"],
        stickers=json.dumps(payload["stickers"], ensure_ascii=False),
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)

    if payload["files"]:
        await _add_template_files(db, db_template, payload["files"])
    if payload["stored_files"]:
        _add_stored_template_files(
            db,
            db_template,
            payload["stored_files"],
            start_order=len(payload["files"])
        )
    if payload["files"] or payload["stored_files"]:
        db.commit()

    db.refresh(db_template)
    template = _template_query(db).filter(Template.id == db_template.id).first()
    return _serialize_template(template)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    db_template = _template_query(db).filter(Template.id == template_id).first()
    if not db_template:
        raise HTTPException(status_code=404, detail="Шаблон не знайдено")

    payload = await _read_template_payload(request)
    keep_file_ids = payload["keep_file_ids"]
    kept_count = len(keep_file_ids) if keep_file_ids is not None else len(db_template.files)
    new_files_count = len(payload["files"]) + len(payload["stored_files"])
    _validate_template_payload(
        payload["name"],
        payload["text"],
        new_files_count,
        kept_count,
        stickers_count=len(payload["stickers"]),
    )

    db_template.name = payload["name"]
    db_template.text = payload["text"]
    db_template.stickers = json.dumps(payload["stickers"], ensure_ascii=False)

    if keep_file_ids is not None:
        keep_ids = set(keep_file_ids)
        for file_item in list(db_template.files):
            if file_item.id not in keep_ids:
                remove_file_quiet(template_file_path(file_item.stored_filename))
                db.delete(file_item)

        kept_files = [item for item in db_template.files if item.id in keep_ids]
        for order, file_item in enumerate(kept_files):
            file_item.file_order = order

        await _add_template_files(db, db_template, payload["files"], start_order=len(kept_files))
        if payload["stored_files"]:
            _add_stored_template_files(
                db,
                db_template,
                payload["stored_files"],
                start_order=len(kept_files) + len(payload["files"])
            )

    db.commit()
    template = _template_query(db).filter(Template.id == template_id).first()
    return _serialize_template(template)


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    db_template = _template_query(db).filter(Template.id == template_id).first()
    if not db_template:
        raise HTTPException(status_code=404, detail="Шаблон не знайдено")

    for file_item in db_template.files:
        remove_file_quiet(template_file_path(file_item.stored_filename))

    db.delete(db_template)
    db.commit()
    return {"message": "Шаблон видалено"}
