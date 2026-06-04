# API для автоповідомлень через Pyrogram
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from typing import List
from pyrogram.errors import FloodWait, RPCError, PeerIdInvalid
from pyrogram import raw
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import asyncio
import hashlib
import json
import os
import time

from database import get_db, SessionLocal
from file_storage import (
    auto_message_file_path,
    remove_file_quiet,
    save_stored_to_auto_message,
    save_upload_to_auto_message,
)
from models import AutoMessage, AutoMessageFile, Group
from schemas import AutoMessageResponse
from pyrogram_client import pyrogram_manager
from logger import log_event
from routers.messages import _detect_kind, send_pyrogram_message
from system_notifications import show_system_notification

router = APIRouter(prefix="/auto-messages", tags=["Автоповідомлення"])

scheduler = AsyncIOScheduler()
CREATE_DUPLICATE_TTL_SECONDS = 15
MAX_STICKERS_PER_AUTO_MESSAGE = 12
_recent_create_fingerprints: dict[str, float] = {}


class ChatPeerUnavailable(RuntimeError):
    pass


class AutoMessageUpdatePayload(BaseModel):
    message: str | None = None
    send_time: str | None = None
    send_day: str | None = None
    repeat_count: int | None = None


DAY_MAP = {
    "понеділок": "mon",
    "вівторок": "tue",
    "середа": "wed",
    "четвер": "thu",
    "п'ятниця": "fri",
    "субота": "sat",
    "неділя": "sun"
}

DAY_MAP_REVERSE = {v: k for k, v in DAY_MAP.items()}

DAY_INDEX = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6
}

DAILY_SEND_DAY = "daily"
DAILY_ALIASES = {
    DAILY_SEND_DAY,
    "щоденно",
    "кожного дня",
    "кожен день",
    "everyday",
    "every day",
}


def _chat_lookup_value(telegram_id: str):
    try:
        return int(telegram_id)
    except (TypeError, ValueError):
        return telegram_id


def _is_peer_id_error(error) -> bool:
    text = str(error) or error.__class__.__name__
    return (
        isinstance(error, PeerIdInvalid)
        or "PEER_ID_INVALID" in text
        or "Peer id invalid" in text
        or "некоректний або недоступний Telegram ID групи" in text
    )


async def _resolve_chat_peer_with_warmup(client, chat_id):
    try:
        return await client.resolve_peer(chat_id)
    except Exception as error:
        if not _is_peer_id_error(error):
            raise

    warmed = await pyrogram_manager.warm_dialogs_now(limit=1000, min_interval=10)
    if not warmed:
        raise ChatPeerUnavailable(f"Telegram peer недоступний: {chat_id}")

    try:
        return await client.resolve_peer(chat_id)
    except Exception as retry_error:
        if _is_peer_id_error(retry_error):
            raise ChatPeerUnavailable(f"Telegram peer недоступний після оновлення діалогів: {chat_id}")
        raise


def _cleanup_recent_fingerprints(now: float):
    expired = [
        fingerprint
        for fingerprint, expires_at in _recent_create_fingerprints.items()
        if expires_at <= now
    ]
    for fingerprint in expired:
        _recent_create_fingerprints.pop(fingerprint, None)


def _upload_fingerprint(upload) -> dict:
    return {
        "filename": getattr(upload, "filename", "") or "",
        "content_type": getattr(upload, "content_type", "") or "",
        "size": getattr(upload, "size", 0) or 0,
    }


def _stored_file_fingerprint(item) -> dict:
    if not isinstance(item, dict):
        return {"invalid": True}
    return {
        "storage": item.get("storage") or "",
        "stored_filename": item.get("stored_filename") or "",
        "filename": item.get("filename") or item.get("original_filename") or "",
        "type": item.get("type") or item.get("content_type") or "",
        "size": item.get("size") or 0,
    }


def _payload_fingerprint(payload) -> str:
    data = {
        "group_id": payload["group_id"],
        "message": payload["message"],
        "send_time": payload["send_time"],
        "send_day": payload["send_day"],
        "repeat_count": payload["repeat_count"],
        "files": [_upload_fingerprint(upload) for upload in payload["files"]],
        "stored_files": [_stored_file_fingerprint(item) for item in payload["stored_files"]],
        "stickers": payload["stickers"],
    }
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reserve_create_fingerprint(payload) -> str:
    now = time.monotonic()
    _cleanup_recent_fingerprints(now)
    fingerprint = _payload_fingerprint(payload)
    if fingerprint in _recent_create_fingerprints:
        raise HTTPException(status_code=409, detail="Таке автоповідомлення вже зберігається")
    _recent_create_fingerprints[fingerprint] = now + CREATE_DUPLICATE_TTL_SECONDS
    return fingerprint


def _release_create_fingerprint(fingerprint: str | None):
    if fingerprint:
        _recent_create_fingerprints.pop(fingerprint, None)


def _normalize_send_day(value: str) -> str:
    day = (value or "").strip().lower()
    if day in DAILY_ALIASES:
        return DAILY_SEND_DAY
    if day in DAY_MAP:
        return day
    if day in DAY_MAP_REVERSE:
        return DAY_MAP_REVERSE[day]
    try:
        repaired = day.encode("latin1").decode("utf-8")
        if repaired in DAILY_ALIASES:
            return DAILY_SEND_DAY
        if repaired in DAY_MAP:
            return repaired
        if repaired in DAY_MAP_REVERSE:
            return DAY_MAP_REVERSE[repaired]
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return day


def _mark_file_exists(auto_msg: AutoMessage):
    auto_msg.files.sort(key=lambda item: (item.file_order or 0, item.id or 0))
    for file_item in auto_msg.files:
        file_item.exists = os.path.exists(auto_message_file_path(file_item.stored_filename))
    return auto_msg


def _auto_message_query(db: Session):
    return db.query(AutoMessage).options(selectinload(AutoMessage.files))


def _sanitize_sticker_items(items) -> list[dict]:
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="stickers має бути списком")

    allowed_fields = {
        "file_id",
        "document_id",
        "id",
        "emoji",
        "mime_type",
        "pack_short_name",
        "thumb_url",
        "animation_url",
        "preview_url",
        "is_animated",
        "is_video",
        "file_name",
    }
    stickers = []
    for item in items[:MAX_STICKERS_PER_AUTO_MESSAGE]:
        if isinstance(item, str):
            file_id = item.strip()
            if file_id:
                stickers.append({"file_id": file_id})
            continue
        if not isinstance(item, dict):
            continue

        cleaned = {
            key: item.get(key)
            for key in allowed_fields
            if item.get(key) not in (None, "")
        }
        file_id = str(cleaned.get("file_id") or "").strip()
        pack = str(cleaned.get("pack_short_name") or "").strip()
        document_id = str(cleaned.get("document_id") or cleaned.get("id") or "").strip()
        if file_id or (pack and document_id):
            if document_id and "document_id" not in cleaned:
                cleaned["document_id"] = document_id
            stickers.append(cleaned)

    return stickers


def _parse_stickers_payload(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return _sanitize_sticker_items(raw)
    try:
        items = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Неправильний формат stickers")
    return _sanitize_sticker_items(items)


def _stickers_from_auto_message(auto_msg: AutoMessage) -> list[dict]:
    return _parse_stickers_payload(getattr(auto_msg, "stickers", "[]") or "[]")


def _serialize_auto_message(auto_msg: AutoMessage):
    auto_msg = _mark_file_exists(auto_msg)
    metadata = {}
    if getattr(auto_msg, "metadata_json", None):
        try:
            metadata = json.loads(auto_msg.metadata_json)
            if not isinstance(metadata, dict):
                metadata = {}
        except Exception:
            metadata = {}
    return {
        "id": auto_msg.id,
        "group_id": auto_msg.group_id,
        "message": auto_msg.message or "",
        "send_time": auto_msg.send_time,
        "send_day": auto_msg.send_day,
        "repeat_count": auto_msg.repeat_count,
        "sent_count": auto_msg.sent_count,
        "is_active": auto_msg.is_active,
        "source": getattr(auto_msg, "source", None) or "manual",
        "parent_report_lesson_id": getattr(auto_msg, "parent_report_lesson_id", None),
        "parent_report_run_id": getattr(auto_msg, "parent_report_run_id", None),
        "scheduled_message_id": getattr(auto_msg, "scheduled_message_id", None),
        "scheduled_target_at": getattr(auto_msg, "scheduled_target_at", None),
        "metadata": metadata,
        "group": auto_msg.group,
        "files": auto_msg.files,
        "stickers": _stickers_from_auto_message(auto_msg),
    }


async def _read_auto_message_payload(request: Request):
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        stored_raw = form.get("stored_files") or "[]"
        try:
            stored_files = json.loads(stored_raw)
            if not isinstance(stored_files, list):
                raise ValueError("stored_files must be a list")
        except Exception:
            raise HTTPException(status_code=400, detail="Неправильний формат stored_files")
        stickers = _parse_stickers_payload(form.get("stickers") or "[]")

        uploads = []
        for item in form.getlist("files"):
            if getattr(item, "filename", None):
                uploads.append(item)

        try:
            group_id = int(form.get("group_id") or 0)
        except Exception:
            group_id = 0
        try:
            repeat_count = int(form.get("repeat_count") or 0)
        except Exception:
            repeat_count = 0

        return {
            "group_id": group_id,
            "message": str(form.get("message") or "").strip(),
            "send_time": str(form.get("send_time") or "").strip(),
            "send_day": str(form.get("send_day") or "").strip(),
            "repeat_count": repeat_count,
            "files": uploads,
            "stored_files": stored_files,
            "stickers": stickers,
        }

    data = await request.json()
    return {
        "group_id": int(data.get("group_id") or 0),
        "message": str(data.get("message") or "").strip(),
        "send_time": str(data.get("send_time") or "").strip(),
        "send_day": str(data.get("send_day") or "").strip(),
        "repeat_count": int(data.get("repeat_count") or 0),
        "files": [],
        "stored_files": [],
        "stickers": _parse_stickers_payload(data.get("stickers") or []),
    }


def _validate_payload(payload):
    payload["send_day"] = _normalize_send_day(payload["send_day"])
    if not payload["group_id"]:
        raise HTTPException(status_code=400, detail="Виберіть групу")
    if not payload["send_time"] or ":" not in payload["send_time"]:
        raise HTTPException(status_code=400, detail="Вкажіть час відправки")
    if payload["send_day"].lower() != DAILY_SEND_DAY and payload["send_day"].lower() not in DAY_MAP:
        raise HTTPException(status_code=400, detail="Вкажіть день відправки")
    if payload["repeat_count"] < 0:
        raise HTTPException(status_code=400, detail="Кількість повторів не може бути від'ємною")
    if not payload["message"] and not payload["files"] and not payload["stored_files"] and not payload["stickers"]:
        raise HTTPException(status_code=400, detail="Додайте текст, файл або наліпку")


async def _add_auto_message_uploads(
    db: Session,
    auto_msg: AutoMessage,
    uploads,
    start_order: int = 0,
    created_paths: list[str] | None = None
):
    for index, upload in enumerate(uploads):
        file_data = await save_upload_to_auto_message(upload, start_order + index)
        if created_paths is not None:
            created_paths.append(auto_message_file_path(file_data["stored_filename"]))
        db_file = AutoMessageFile(auto_message_id=auto_msg.id, **file_data)
        db.add(db_file)


def _add_auto_message_stored_files(
    db: Session,
    auto_msg: AutoMessage,
    stored_files,
    start_order: int = 0,
    created_paths: list[str] | None = None
):
    for index, item in enumerate(stored_files):
        if not isinstance(item, dict):
            continue
        try:
            file_data = save_stored_to_auto_message(item, start_order + index)
        except FileNotFoundError:
            filename = item.get("filename") or item.get("stored_filename") or "file"
            raise HTTPException(status_code=400, detail=f"Файл не знайдено: {filename}")
        except Exception as error:
            filename = item.get("filename") or item.get("stored_filename") or "file"
            raise HTTPException(status_code=400, detail=f"Не вдалося додати файл {filename}: {error}")
        if created_paths is not None:
            created_paths.append(auto_message_file_path(file_data["stored_filename"]))
        db_file = AutoMessageFile(auto_message_id=auto_msg.id, **file_data)
        db.add(db_file)


def _file_data_from_auto_message(auto_msg: AutoMessage):
    file_data_list = []
    missing = []

    for file_item in sorted(auto_msg.files, key=lambda item: (item.file_order or 0, item.id or 0)):
        path = auto_message_file_path(file_item.stored_filename)
        if not os.path.exists(path):
            missing.append(file_item.original_filename)
            continue
        data = {
            "filename": file_item.original_filename,
            "path": path,
            "type": file_item.content_type or "application/octet-stream",
            "stored": True,
            "storage": "auto",
            "stored_filename": file_item.stored_filename,
        }
        data["kind"] = _detect_kind(data)
        file_data_list.append(data)

    if missing:
        log_event(
            "WARNING",
            "AutoMsg",
            f"Файли автоповідомлення #{auto_msg.id} не знайдено: {', '.join(missing)}"
        )

    return file_data_list


def _next_target_datetime(auto_msg: AutoMessage):
    now = datetime.now()
    send_day = _normalize_send_day(auto_msg.send_day)
    try:
        hour, minute = map(int, auto_msg.send_time.split(":"))
    except Exception:
        return None

    if send_day == DAILY_SEND_DAY:
        target_datetime = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_datetime <= now:
            target_datetime += timedelta(days=1)
        return target_datetime

    day_cron = DAY_MAP.get(send_day)
    if not day_cron:
        return None

    target_day_idx = DAY_INDEX.get(day_cron, 0)
    current_day_idx = now.weekday()
    days_ahead = target_day_idx - current_day_idx
    if days_ahead < 0:
        days_ahead += 7

    target_datetime = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if target_datetime <= now:
        target_datetime += timedelta(days=7)
    return target_datetime


async def get_scheduled_for_chat(client, chat_id: int) -> list:
    try:
        peer = await _resolve_chat_peer_with_warmup(client, chat_id)
        history = await client.invoke(
            raw.functions.messages.GetScheduledHistory(peer=peer, hash=0)
        )
        texts = []
        if history and hasattr(history, "messages"):
            for sm in history.messages:
                sm_text = getattr(sm, "message", "") or ""
                texts.append(sm_text.strip())
        return texts
    except ChatPeerUnavailable:
        raise
    except Exception as e:
        if _is_peer_id_error(e):
            raise ChatPeerUnavailable(f"Telegram peer недоступний: {chat_id}") from e
        log_event("WARNING", "AutoMsg", f"Не вдалося отримати відкладені повідомлення: {e}")
        return []


async def _delete_scheduled_telegram_message(auto_msg: AutoMessage, group: Group) -> bool:
    message_id = getattr(auto_msg, "scheduled_message_id", None)
    if not message_id or not pyrogram_manager.is_connected:
        return False

    client = pyrogram_manager.client
    chat_id = _chat_lookup_value(group.telegram_id)
    peer = await _resolve_chat_peer_with_warmup(client, chat_id)
    await client.invoke(
        raw.functions.messages.DeleteScheduledMessages(peer=peer, id=[int(message_id)])
    )
    auto_msg.scheduled_message_id = None
    auto_msg.last_scheduled_for = None
    auto_msg.scheduled_target_at = None
    return True


async def _edit_scheduled_telegram_message(auto_msg: AutoMessage, group: Group, target_datetime: datetime) -> bool:
    message_id = getattr(auto_msg, "scheduled_message_id", None)
    if not message_id or not pyrogram_manager.is_connected:
        return False
    if auto_msg.files or _stickers_from_auto_message(auto_msg):
        return False

    client = pyrogram_manager.client
    chat_id = _chat_lookup_value(group.telegram_id)
    peer = await _resolve_chat_peer_with_warmup(client, chat_id)
    await client.invoke(
        raw.functions.messages.EditMessage(
            peer=peer,
            id=int(message_id),
            message=auto_msg.message or "",
            schedule_date=int(target_datetime.timestamp()),
        )
    )
    target_key = target_datetime.isoformat(timespec="minutes")
    auto_msg.last_scheduled_for = target_key
    auto_msg.scheduled_target_at = target_datetime.isoformat(timespec="minutes")
    return True


async def _schedule_in_telegram(auto_msg: AutoMessage, group: Group, target_datetime: datetime, scheduled_cache=None):
    client = pyrogram_manager.client
    chat_id = _chat_lookup_value(group.telegram_id)
    message_key = (auto_msg.message or "").strip()
    target_key = target_datetime.isoformat(timespec="minutes")

    if getattr(auto_msg, "last_scheduled_for", None) == target_key:
        return "skipped"

    if message_key:
        if scheduled_cache is not None:
            if chat_id not in scheduled_cache:
                scheduled_cache[chat_id] = await get_scheduled_for_chat(client, chat_id)
            if message_key in scheduled_cache[chat_id]:
                return "skipped"
        else:
            scheduled_texts = await get_scheduled_for_chat(client, chat_id)
            if message_key in scheduled_texts:
                return "skipped"

    file_data_list = _file_data_from_auto_message(auto_msg)
    sticker_items = _stickers_from_auto_message(auto_msg)
    if not message_key and not file_data_list and not sticker_items:
        return "empty"

    if not message_key:
        await _resolve_chat_peer_with_warmup(client, chat_id)

    result = await send_pyrogram_message(
        group.telegram_id,
        auto_msg.message or "",
        file_data_list if file_data_list else None,
        prefer_cached=False,
        schedule_date=target_datetime,
        sticker_file_ids=sticker_items,
    )
    if not result["ok"] and _is_peer_id_error(result.get("description", "")):
        await pyrogram_manager.warm_dialogs_now(limit=1000, min_interval=10)
        result = await send_pyrogram_message(
            group.telegram_id,
            auto_msg.message or "",
            file_data_list if file_data_list else None,
            prefer_cached=False,
            schedule_date=target_datetime,
            sticker_file_ids=sticker_items,
        )
    if not result["ok"]:
        if _is_peer_id_error(result.get("description", "")):
            raise ChatPeerUnavailable(f"Telegram peer недоступний: {chat_id}")
        raise RuntimeError(result.get("description") or "Не вдалося запланувати повідомлення")

    if message_key and scheduled_cache is not None:
        scheduled_cache.setdefault(chat_id, []).append(message_key)

    message_ids = result.get("message_ids") or []
    if message_ids:
        auto_msg.scheduled_message_id = int(message_ids[0])
    auto_msg.last_scheduled_for = target_key
    auto_msg.scheduled_target_at = target_datetime.isoformat(timespec="minutes")
    return "scheduled"


async def send_auto_message_pyrogram(auto_message_id: int):
    db = SessionLocal()
    try:
        auto_msg = _auto_message_query(db).filter(AutoMessage.id == auto_message_id).first()
        if not auto_msg or not auto_msg.is_active:
            return

        group = db.query(Group).filter(Group.id == auto_msg.group_id).first()
        if not group:
            log_event("ERROR", "AutoMsg", f"Помилка: групу не знайдено (group_id={auto_msg.group_id})")
            return

        if not pyrogram_manager.is_connected:
            log_event("WARNING", "AutoMsg", f"Pyrogram не підключено, повідомлення пропущено: '{group.name}'")
            return

        auto_msg.sent_count += 1
        log_event("INFO", "AutoMsg", f"Час відправки настав для '{group.name}' (msg_id={auto_message_id}, відправлено: {auto_msg.sent_count})")

        if auto_msg.repeat_count > 0 and auto_msg.sent_count >= auto_msg.repeat_count:
            auto_msg.is_active = 0
            job_id = f"auto_msg_{auto_message_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            log_event("INFO", "AutoMsg", f"Ліміт досягнуто ({auto_msg.repeat_count}), деактивовано msg_id={auto_message_id}")
        else:
            try:
                next_target = _next_target_datetime(auto_msg)
                if not next_target:
                    raise RuntimeError("Некоректний день відправки")
                status = await _schedule_in_telegram(auto_msg, group, next_target)
                if status == "scheduled":
                    log_event("INFO", "AutoMsg", f"Заплановано НАСТУПНЕ: '{group.name}' на {next_target.strftime('%d.%m %H:%M')}")
                    show_system_notification(
                        "Автоповідомлення оброблено",
                        f"{group.name}: наступне повідомлення додано на {next_target.strftime('%d.%m %H:%M')}",
                    )
                elif status == "skipped":
                    log_event("INFO", "AutoMsg", f"Вже заплановано для '{group.name}', пропускаємо")
            except ChatPeerUnavailable:
                log_event(
                    "WARNING",
                    "AutoMsg",
                    f"Telegram ще не бачить групу '{group.name}' після перезапуску. Синхронізуйте групи або відкрийте цю групу в Telegram, якщо попередження повторюється."
                )
            except PeerIdInvalid:
                log_event("WARNING", "AutoMsg", f"Група '{group.name}' не знайдена в сесії Telegram. Повідомлення пропущено.")
            except FloodWait as e:
                log_event("WARNING", "AutoMsg", f"FloodWait {e.value}с при плануванні наступного")
                await asyncio.sleep(e.value)
            except Exception as e:
                log_event("WARNING", "AutoMsg", f"Не вдалося запланувати наступне: {e}")

        db.commit()
    except Exception as e:
        log_event("ERROR", "AutoMsg", f"Критична помилка: {e}")
    finally:
        db.close()


async def schedule_telegram_messages():
    if not pyrogram_manager.is_connected:
        log_event("INFO", "AutoMsg", "Pyrogram не підключено — відкладені повідомлення не заплановано")
        return {"scheduled_count": 0, "skipped_count": 0, "error_count": 0}

    db = SessionLocal()
    try:
        auto_msgs = _auto_message_query(db).filter(AutoMessage.is_active == 1).all()
        if not auto_msgs:
            return {"scheduled_count": 0, "skipped_count": 0, "error_count": 0}

        scheduled_count = 0
        skipped_count = 0
        error_count = 0
        scheduled_cache = {}

        for auto_msg in auto_msgs:
            group = db.query(Group).filter(Group.id == auto_msg.group_id).first()
            if not group:
                continue

            target_datetime = _next_target_datetime(auto_msg)
            if not target_datetime:
                continue

            try:
                status = await _schedule_in_telegram(auto_msg, group, target_datetime, scheduled_cache)
                if status == "scheduled":
                    scheduled_count += 1
                    db.commit()
                    log_event("INFO", "AutoMsg", f"Заплановано: '{group.name}' на {target_datetime.strftime('%d.%m %H:%M')}")
                elif status == "skipped":
                    skipped_count += 1

                await asyncio.sleep(0.3)
            except ChatPeerUnavailable:
                error_count += 1
                log_event(
                    "WARNING",
                    "AutoMsg",
                    f"Telegram ще не бачить групу '{group.name}' після перезапуску. Спробуйте синхронізувати групи, якщо повториться."
                )
            except PeerIdInvalid:
                error_count += 1
                log_event("WARNING", "AutoMsg", f"Група '{group.name}' не знайдена в сесії Telegram. Відкрийте її в Telegram хоча б один раз.")
            except FloodWait as e:
                error_count += 1
                log_event("WARNING", "AutoMsg", f"FloodWait {e.value}с при плануванні")
                await asyncio.sleep(e.value)
            except RPCError as e:
                error_count += 1
                log_event("ERROR", "AutoMsg", f"Не вдалося запланувати для '{group.name}': {e}")
            except Exception as e:
                error_count += 1
                log_event("ERROR", "AutoMsg", f"Помилка планування для '{group.name}': {e}")

        if scheduled_count > 0:
            log_event("INFO", "AutoMsg", f"Заплановано {scheduled_count} відкладених повідомлень через Telegram")
        if skipped_count > 0:
            log_event("INFO", "AutoMsg", f"Пропущено {skipped_count} (вже заплановані в Telegram)")
        if scheduled_count > 0 or skipped_count > 0:
            show_system_notification(
                "Автоповідомлення заплановано",
                f"Додано {scheduled_count} повідомлень у Telegram, пропущено {skipped_count} вже запланованих.",
            )
        return {
            "scheduled_count": scheduled_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
        }
    finally:
        db.close()


async def schedule_created_auto_message_in_telegram(auto_message_id: int):
    start_time = time.perf_counter()
    if not pyrogram_manager.is_connected:
        log_event(
            "INFO",
            "AutoMsg",
            f"Telegram-планування автоповідомлення #{auto_message_id} пропущено: Pyrogram не підключено"
        )
        return

    db = SessionLocal()
    try:
        auto_msg = _auto_message_query(db).filter(AutoMessage.id == auto_message_id).first()
        if not auto_msg or not auto_msg.is_active:
            log_event(
                "INFO",
                "AutoMsg",
                f"Фонове Telegram-планування пропущено: автоповідомлення #{auto_message_id} вже не активне"
            )
            return

        group = db.query(Group).filter(Group.id == auto_msg.group_id).first()
        if not group:
            log_event("WARNING", "AutoMsg", f"Фонове Telegram-планування не виконано: групу не знайдено для msg_id={auto_message_id}")
            return

        target_datetime = _next_target_datetime(auto_msg)
        if not target_datetime:
            log_event("WARNING", "AutoMsg", f"Фонове Telegram-планування не виконано: некоректний день для msg_id={auto_message_id}")
            return

        status = await _schedule_in_telegram(auto_msg, group, target_datetime)
        elapsed = time.perf_counter() - start_time
        if status == "scheduled":
            db.commit()
            log_event(
                "INFO",
                "AutoMsg",
                f"Фонове Telegram-планування виконано для '{group.name}' на {target_datetime.strftime('%d.%m %H:%M')} за {elapsed:.2f} с"
            )
            show_system_notification(
                "Автоповідомлення заплановано",
                f"{group.name}: {target_datetime.strftime('%d.%m %H:%M')}",
            )
        elif status == "skipped":
            log_event("INFO", "AutoMsg", f"Фонове Telegram-планування пропущено для '{group.name}': вже заплановано ({elapsed:.2f} с)")
        else:
            log_event("INFO", "AutoMsg", f"Фонове Telegram-планування пропущено для '{group.name}': немає вмісту ({elapsed:.2f} с)")
    except ChatPeerUnavailable:
        elapsed = time.perf_counter() - start_time
        log_event(
            "WARNING",
            "AutoMsg",
            f"Не вдалося фоново запланувати автоповідомлення #{auto_message_id} за {elapsed:.2f} с: Telegram ще не бачить цю групу після перезапуску"
        )
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        log_event("WARNING", "AutoMsg", f"Не вдалося фоново запланувати автоповідомлення #{auto_message_id} через Telegram за {elapsed:.2f} с: {e}")
    finally:
        db.close()


def schedule_auto_message(auto_message: AutoMessage):
    job_id = f"auto_msg_{auto_message.id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    hour, minute = auto_message.send_time.split(":")
    send_day = _normalize_send_day(auto_message.send_day)
    trigger_kwargs = {
        "hour": int(hour),
        "minute": int(minute),
    }
    if send_day != DAILY_SEND_DAY:
        trigger_kwargs["day_of_week"] = DAY_MAP.get(send_day, "mon")

    trigger = CronTrigger(**trigger_kwargs)

    scheduler.add_job(
        send_auto_message_pyrogram,
        trigger,
        args=[auto_message.id],
        id=job_id
    )


@router.get("/", response_model=List[AutoMessageResponse])
def get_all_auto_messages(db: Session = Depends(get_db)):
    auto_messages = _auto_message_query(db).all()
    return [_serialize_auto_message(auto_msg) for auto_msg in auto_messages]


@router.post("/", response_model=AutoMessageResponse)
async def create_auto_message(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    start_time = time.perf_counter()
    payload = await _read_auto_message_payload(request)
    _validate_payload(payload)

    group = db.query(Group).filter(Group.id == payload["group_id"]).first()
    if not group:
        raise HTTPException(status_code=404, detail="Групу не знайдено")

    fingerprint = _reserve_create_fingerprint(payload)
    db_auto_msg = None
    created_file_paths = []
    files_count = len(payload["files"]) + len(payload["stored_files"])
    stickers_count = len(payload["stickers"])

    try:
        db_auto_msg = AutoMessage(
            group_id=payload["group_id"],
            message=payload["message"],
            send_time=payload["send_time"],
            send_day=payload["send_day"],
            repeat_count=payload["repeat_count"],
            stickers=json.dumps(payload["stickers"], ensure_ascii=False),
        )
        db.add(db_auto_msg)
        db.commit()
        db.refresh(db_auto_msg)

        if payload["files"]:
            await _add_auto_message_uploads(
                db,
                db_auto_msg,
                payload["files"],
                created_paths=created_file_paths
            )
        if payload["stored_files"]:
            _add_auto_message_stored_files(
                db,
                db_auto_msg,
                payload["stored_files"],
                start_order=len(payload["files"]),
                created_paths=created_file_paths
            )
        if payload["files"] or payload["stored_files"]:
            db.commit()
    except Exception:
        _release_create_fingerprint(fingerprint)
        db.rollback()
        for path in created_file_paths:
            remove_file_quiet(path)
        if db_auto_msg and db_auto_msg.id:
            db_auto_msg = _auto_message_query(db).filter(AutoMessage.id == db_auto_msg.id).first()
            if db_auto_msg:
                for file_item in db_auto_msg.files:
                    remove_file_quiet(auto_message_file_path(file_item.stored_filename))
                db.delete(db_auto_msg)
                db.commit()
        raise

    db_auto_msg = _auto_message_query(db).filter(AutoMessage.id == db_auto_msg.id).first()
    schedule_auto_message(db_auto_msg)

    telegram_queued = bool(pyrogram_manager.is_connected)
    if telegram_queued:
        background_tasks.add_task(schedule_created_auto_message_in_telegram, db_auto_msg.id)

    elapsed = time.perf_counter() - start_time
    log_event(
        "INFO",
        "AutoMsg",
        f"Автоповідомлення #{db_auto_msg.id} збережено за {elapsed:.2f} с; файлів: {files_count}; наліпок: {stickers_count}; Telegram-планування: {'у фоні' if telegram_queued else 'не підключено'}"
    )

    return _serialize_auto_message(db_auto_msg)


@router.delete("/{auto_message_id}")
async def delete_auto_message(auto_message_id: int, db: Session = Depends(get_db)):
    db_auto_msg = _auto_message_query(db).filter(AutoMessage.id == auto_message_id).first()
    if not db_auto_msg:
        raise HTTPException(status_code=404, detail="Автоповідомлення не знайдено")

    job_id = f"auto_msg_{auto_message_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    group = db.query(Group).filter(Group.id == db_auto_msg.group_id).first()
    if group:
        try:
            await _delete_scheduled_telegram_message(db_auto_msg, group)
        except Exception as error:
            log_event("WARNING", "AutoMsg", f"Не вдалося видалити відкладене повідомлення #{auto_message_id} у Telegram: {error}")

    for file_item in db_auto_msg.files:
        remove_file_quiet(auto_message_file_path(file_item.stored_filename))

    db.delete(db_auto_msg)
    db.commit()
    return {"message": "Автоповідомлення видалено"}


@router.put("/{auto_message_id}", response_model=AutoMessageResponse)
async def update_auto_message(auto_message_id: int, payload: AutoMessageUpdatePayload, db: Session = Depends(get_db)):
    db_auto_msg = _auto_message_query(db).filter(AutoMessage.id == auto_message_id).first()
    if not db_auto_msg:
        raise HTTPException(status_code=404, detail="Автоповідомлення не знайдено")

    data = payload.model_dump(exclude_unset=True)
    if "message" in data and data["message"] is not None:
        db_auto_msg.message = str(data["message"]).strip()
    if "send_time" in data and data["send_time"] is not None:
        send_time = str(data["send_time"]).strip()
        if ":" not in send_time:
            raise HTTPException(status_code=400, detail="Вкажіть час відправки")
        db_auto_msg.send_time = send_time
    if "send_day" in data and data["send_day"] is not None:
        send_day = _normalize_send_day(str(data["send_day"]))
        if send_day != DAILY_SEND_DAY and send_day not in DAY_MAP:
            raise HTTPException(status_code=400, detail="Вкажіть день відправки")
        db_auto_msg.send_day = send_day
    if "repeat_count" in data and data["repeat_count"] is not None:
        repeat_count = int(data["repeat_count"])
        if repeat_count < 0:
            raise HTTPException(status_code=400, detail="Кількість повторів не може бути від'ємною")
        db_auto_msg.repeat_count = repeat_count

    if not (db_auto_msg.message or "").strip() and not db_auto_msg.files and not _stickers_from_auto_message(db_auto_msg):
        raise HTTPException(status_code=400, detail="Додайте текст, файл або наліпку")

    group = db.query(Group).filter(Group.id == db_auto_msg.group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Групу не знайдено")

    edited_in_telegram = False
    if db_auto_msg.is_active:
        target_datetime = _next_target_datetime(db_auto_msg)
        if not target_datetime:
            raise HTTPException(status_code=400, detail="Некоректний день або час відправки")

        if getattr(db_auto_msg, "scheduled_message_id", None):
            try:
                edited_in_telegram = await _edit_scheduled_telegram_message(db_auto_msg, group, target_datetime)
            except Exception as error:
                db.rollback()
                log_event("WARNING", "AutoMsg", f"Не вдалося оновити відкладене повідомлення #{auto_message_id} у Telegram: {error}")
                raise HTTPException(status_code=502, detail=f"Не вдалося оновити повідомлення в Telegram: {error}") from error

        if not edited_in_telegram:
            db_auto_msg.last_scheduled_for = None
            db_auto_msg.scheduled_message_id = None
            db_auto_msg.scheduled_target_at = None

    db.commit()
    db.refresh(db_auto_msg)

    if db_auto_msg.is_active:
        schedule_auto_message(db_auto_msg)
        if not edited_in_telegram and pyrogram_manager.is_connected:
            await schedule_created_auto_message_in_telegram(db_auto_msg.id)
            db.refresh(db_auto_msg)

    log_event("INFO", "AutoMsg", f"Автоповідомлення #{auto_message_id} оновлено")
    return _serialize_auto_message(db_auto_msg)


@router.put("/{auto_message_id}/toggle")
async def toggle_auto_message(auto_message_id: int, db: Session = Depends(get_db)):
    db_auto_msg = db.query(AutoMessage).filter(AutoMessage.id == auto_message_id).first()
    if not db_auto_msg:
        raise HTTPException(status_code=404, detail="Автоповідомлення не знайдено")

    was_active = bool(db_auto_msg.is_active)
    db_auto_msg.is_active = 0 if was_active else 1

    if was_active:
        group = db.query(Group).filter(Group.id == db_auto_msg.group_id).first()
        if group:
            try:
                await _delete_scheduled_telegram_message(db_auto_msg, group)
            except Exception as error:
                log_event("WARNING", "AutoMsg", f"Не вдалося прибрати відкладене повідомлення #{auto_message_id} у Telegram: {error}")
        job_id = f"auto_msg_{auto_message_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    else:
        db_auto_msg.last_scheduled_for = None
        db_auto_msg.scheduled_message_id = None
        db_auto_msg.scheduled_target_at = None
        schedule_auto_message(db_auto_msg)

    db.commit()

    if db_auto_msg.is_active and pyrogram_manager.is_connected:
        await schedule_created_auto_message_in_telegram(db_auto_msg.id)

    return {"message": "Статус змінено", "is_active": db_auto_msg.is_active}


@router.post("/schedule-all")
async def schedule_all_messages():
    if not pyrogram_manager.is_connected:
        raise HTTPException(status_code=400, detail="Pyrogram не підключено")

    await schedule_telegram_messages()
    return {"message": "Відкладені повідомлення заплановано через Telegram"}


def init_scheduler(db: Session):
    auto_messages = db.query(AutoMessage).filter(AutoMessage.is_active == 1).all()
    for auto_msg in auto_messages:
        schedule_auto_message(auto_msg)
    if auto_messages:
        log_event("INFO", "System", f"Завантажено {len(auto_messages)} автоповідомлень в локальний планувальник")
