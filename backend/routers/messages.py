from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InputMediaDocument, InputMediaPhoto, InputMediaVideo
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import hashlib
import httpx
import json
import os
import re
import shutil
import tempfile
import time
from urllib.parse import urlparse

from database import get_db
from file_storage import (
    MAX_REMOTE_IMPORT_BYTES,
    filename_from_url,
    import_file_path,
    remove_file_quiet,
    stored_file_path,
    unique_stored_name,
)
from logger import log_event
from models import Group
from pyrogram_client import pyrogram_manager
from routers.stickers import refresh_sticker_file_id, resolve_sticker_file_id

router = APIRouter(prefix="/messages", tags=["Повідомлення"])

CONCURRENT_LIMIT_TEXT = 10
CONCURRENT_LIMIT_MEDIA = 4
STAGGER_DELAY = 0.12
MAX_RETRIES = 3
MEDIA_GROUP_LIMIT = 10
CAPTION_LIMIT = 1024
FILE_READ_CHUNK_SIZE = 1024 * 1024
MAX_STICKERS_PER_SEND = 12
PHOTO_AS_DOCUMENT_ERRORS = (
    "PHOTO_INVALID_DIMENSIONS",
    "PHOTO_EXT_INVALID",
    "PHOTO_INVALID",
    "IMAGE_PROCESS_FAILED",
    "MEDIA_INVALID",
)
REMOTE_IMPORT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/pdf": ".pdf",
}


class ImportUrlRequest(BaseModel):
    url: str
    filename: Optional[str] = None


def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _safe_filename(filename: str, fallback: str) -> str:
    name = os.path.basename(filename or fallback)
    return "".join("_" if ch in '<>:"/\\|?*' else ch for ch in name) or fallback


def _content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
    if not match:
        match = re.search(r'filename="?([^";]+)"?', value, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _filename_with_content_type_extension(filename: str, content_type: str) -> str:
    if os.path.splitext(filename)[1]:
        return filename
    extension = REMOTE_IMPORT_EXTENSIONS.get((content_type or "").split(";")[0].lower())
    return f"{filename}{extension}" if extension else filename


def _content_addressed_import_name(filename: str, digest: str) -> str:
    stem, ext = os.path.splitext(_safe_filename(filename, "imported_file"))
    stem = stem[:80] or "imported_file"
    ext = ext[:20]
    return f"import_{digest[:16]}_{stem}{ext}"


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(FILE_READ_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _find_matching_import_file(folder: str, expected_digest: str, expected_size: int, exclude_path: str) -> str | None:
    try:
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            path = os.path.abspath(entry.path)
            if path == os.path.abspath(exclude_path):
                continue
            try:
                if entry.stat().st_size != expected_size:
                    continue
                if _file_digest(path) == expected_digest:
                    return path
            except OSError:
                continue
    except OSError:
        return None
    return None


def _detect_kind(file_data: dict) -> str:
    content_type = (file_data.get("type") or "").lower()
    filename = (file_data.get("filename") or "").lower()

    if content_type == "image/gif" or filename.endswith(".gif"):
        return "animation"
    if content_type.startswith("image/"):
        return "photo"
    if content_type.startswith("video/"):
        return "video"
    return "document"


def _media_value(file_data: dict, prefer_cached: bool, as_document: bool = False):
    if prefer_cached and as_document and file_data.get("document_file_id"):
        return file_data["document_file_id"]
    if prefer_cached and file_data.get("file_id"):
        return file_data["file_id"]
    return file_data["path"]


def _message_media(message, kind: str):
    if not message:
        return None
    if kind == "photo":
        return getattr(message, "photo", None)
    if kind == "video":
        return getattr(message, "video", None)
    if kind == "animation":
        return getattr(message, "animation", None) or getattr(message, "document", None)
    return getattr(message, "document", None)


def _remember_file_id(file_data: dict, message, stored_kind: str | None = None):
    stored_kind = stored_kind or file_data["kind"]
    media = _message_media(message, stored_kind)
    file_id = getattr(media, "file_id", None)
    if file_id:
        if stored_kind == "document" and file_data["kind"] != "document":
            file_data["document_file_id"] = file_id
            file_data["force_document"] = True
        else:
            file_data["file_id"] = file_id


def _is_photo_as_document_error(error: Exception) -> bool:
    text = str(error) or error.__class__.__name__
    return any(code in text for code in PHOTO_AS_DOCUMENT_ERRORS)


def _error_text(error: Exception) -> str:
    text = str(error) or error.__class__.__name__
    known = {
        "CHAT_WRITE_FORBIDDEN": "немає права писати в цю групу/канал",
        "USER_BANNED_IN_CHANNEL": "акаунт обмежений у цій групі/каналі",
        "PEER_ID_INVALID": "некоректний або недоступний Telegram ID групи",
        "CHAT_ADMIN_REQUIRED": "потрібні права адміністратора",
        "MEDIA_CAPTION_TOO_LONG": "підпис до файлу занадто довгий",
        "MESSAGE_TOO_LONG": "текст повідомлення занадто довгий",
        "FILE_PARTS_INVALID": "файл завеликий або пошкоджений",
        "PHOTO_INVALID_DIMENSIONS": "некоректний розмір зображення",
        "WEBPAGE_CURL_FAILED": "Telegram не зміг отримати файл за посиланням",
    }
    for code, description in known.items():
        if code in text:
            return f"{description} ({code})"
    if "Peer id invalid" in text:
        return "некоректний або недоступний Telegram ID групи (PEER_ID_INVALID)"
    return text


async def _ensure_client_user(client):
    if getattr(client, "me", None) is None:
        client.me = await client.get_me()


async def _send_single_file(
    client,
    chat: int,
    file_data: dict,
    caption: str | None,
    prefer_cached: bool,
    as_document: bool = False,
    schedule_date=None
):
    as_document = as_document or file_data.get("force_document", False)
    value = _media_value(file_data, prefer_cached, as_document=as_document)
    kind = file_data["kind"]

    if as_document or kind == "document":
        message = await client.send_document(
            chat,
            value,
            caption=caption,
            file_name=file_data.get("filename"),
            schedule_date=schedule_date
        )
        _remember_file_id(file_data, message, "document")
    elif kind == "photo":
        message = await client.send_photo(chat, value, caption=caption, schedule_date=schedule_date)
        _remember_file_id(file_data, message)
    elif kind == "video":
        message = await client.send_video(chat, value, caption=caption, schedule_date=schedule_date)
        _remember_file_id(file_data, message)
    elif kind == "animation":
        message = await client.send_animation(chat, value, caption=caption, schedule_date=schedule_date)
        _remember_file_id(file_data, message)

    return [message]


async def _send_media_album(client, chat: int, files: list, caption: str | None, prefer_cached: bool, schedule_date=None):
    if len(files) == 1:
        return await _send_single_file(client, chat, files[0], caption, prefer_cached, schedule_date=schedule_date)

    if any(file_data.get("force_document") for file_data in files):
        return await _send_document_album(client, chat, files, caption, prefer_cached, schedule_date=schedule_date)

    media_group = []
    for i, file_data in enumerate(files):
        item_caption = caption if i == 0 else None
        value = _media_value(file_data, prefer_cached)
        if file_data["kind"] == "photo":
            media_group.append(InputMediaPhoto(value, caption=item_caption))
        else:
            media_group.append(InputMediaVideo(value, caption=item_caption))

    try:
        messages = await client.send_media_group(chat, media_group, schedule_date=schedule_date)
    except Exception as error:
        if any(file_data["kind"] == "photo" for file_data in files) and _is_photo_as_document_error(error):
            for file_data in files:
                if file_data["kind"] == "photo":
                    file_data["force_document"] = True
            log_event(
                "WARNING",
                "Send",
                f"Telegram відхилив фотоальбом ({_error_text(error)}); відправляю ці фото як файли"
            )
            return await _send_document_album(client, chat, files, caption, prefer_cached, schedule_date=schedule_date)
        raise

    for file_data, message in zip(files, messages):
        _remember_file_id(file_data, message)
    return messages


async def _send_document_album(client, chat: int, files: list, caption: str | None, prefer_cached: bool, schedule_date=None):
    if len(files) == 1:
        return await _send_single_file(client, chat, files[0], caption, prefer_cached, as_document=True, schedule_date=schedule_date)

    media_group = []
    for i, file_data in enumerate(files):
        item_caption = caption if i == 0 else None
        media_group.append(
            InputMediaDocument(
                _media_value(file_data, prefer_cached, as_document=True),
                caption=item_caption
            )
        )

    try:
        messages = await client.send_media_group(chat, media_group, schedule_date=schedule_date)
    except Exception as error:
        if not _is_photo_as_document_error(error):
            raise

        messages = []
        for i, file_data in enumerate(files):
            item_caption = caption if i == 0 else None
            messages.extend(
                await _send_single_file(
                    client,
                    chat,
                    file_data,
                    item_caption,
                    prefer_cached,
                    as_document=True,
                    schedule_date=schedule_date
                )
            )
        return messages

    for file_data, message in zip(files, messages):
        _remember_file_id(file_data, message, "document")
    return messages


async def _send_files(client, chat: int, text: str, file_data_list: list, prefer_cached: bool, schedule_date=None):
    media_files = [f for f in file_data_list if f["kind"] in ("photo", "video")]
    document_files = [f for f in file_data_list if f["kind"] == "document"]
    animation_files = [f for f in file_data_list if f["kind"] == "animation"]

    caption_text = text if text and len(text) <= CAPTION_LIMIT else None
    if text and not caption_text:
        await client.send_message(chat, text, schedule_date=schedule_date)

    caption_used = False

    for files in _chunked(media_files, MEDIA_GROUP_LIMIT):
        caption = caption_text if not caption_used else None
        await _send_media_album(client, chat, files, caption, prefer_cached, schedule_date=schedule_date)
        caption_used = caption_used or bool(caption)

    for files in _chunked(document_files, MEDIA_GROUP_LIMIT):
        caption = caption_text if not caption_used else None
        await _send_document_album(client, chat, files, caption, prefer_cached, schedule_date=schedule_date)
        caption_used = caption_used or bool(caption)

    for file_data in animation_files:
        caption = caption_text if not caption_used else None
        await _send_single_file(client, chat, file_data, caption, prefer_cached, schedule_date=schedule_date)
        caption_used = caption_used or bool(caption)


async def _send_stickers(client, chat: int, stickers: list, schedule_date=None):
    for sticker in stickers:
        sticker_file_id = await resolve_sticker_file_id(sticker)
        if not sticker_file_id:
            continue

        try:
            await client.send_sticker(chat, sticker_file_id, schedule_date=schedule_date)
        except RPCError:
            if not isinstance(sticker, dict):
                raise
            pack = str(sticker.get("pack_short_name") or "").strip()
            document_id = str(sticker.get("document_id") or sticker.get("id") or "").strip()
            refreshed_file_id = await refresh_sticker_file_id(pack, document_id)
            if not refreshed_file_id:
                raise
            sticker["file_id"] = refreshed_file_id
            await client.send_sticker(chat, refreshed_file_id, schedule_date=schedule_date)


async def send_pyrogram_message(
    chat_id: str,
    text: str,
    file_data_list: list | None = None,
    prefer_cached: bool = True,
    schedule_date=None,
    sticker_file_ids: list | None = None
) -> dict:
    client = pyrogram_manager.client
    if not client or not pyrogram_manager.is_connected:
        return {"ok": False, "description": "Pyrogram не підключено"}

    chat = int(chat_id)
    sticker_file_ids = sticker_file_ids or []
    if not text and not file_data_list and not sticker_file_ids:
        return {"ok": False, "description": "Немає тексту, файлів або наліпок для відправки"}

    for attempt in range(MAX_RETRIES):
        try:
            if not file_data_list:
                if text:
                    await client.send_message(chat, text, schedule_date=schedule_date)
            else:
                await _ensure_client_user(client)
                await _send_files(client, chat, text, file_data_list, prefer_cached, schedule_date=schedule_date)

            if sticker_file_ids:
                await _send_stickers(client, chat, sticker_file_ids, schedule_date=schedule_date)

            return {"ok": True, "description": "OK"}

        except FloodWait as error:
            if attempt >= MAX_RETRIES - 1:
                return {
                    "ok": False,
                    "description": f"Telegram просить зачекати {error.value} с; спроби вичерпано"
                }
            await asyncio.sleep(error.value)

        except RPCError as error:
            return {"ok": False, "description": _error_text(error)}

        except Exception as error:
            return {"ok": False, "description": _error_text(error)}

    return {"ok": False, "description": "Не вдалося відправити після повторних спроб"}


async def _send_to_one_group_inner(group, message, file_data_list, sticker_file_ids, index, total, prefer_cached: bool):
    print(f"[Send] Sending to '{group.name}' [{index + 1}/{total}]")

    result = await send_pyrogram_message(
        group.telegram_id,
        message,
        file_data_list if file_data_list else None,
        prefer_cached=prefer_cached,
        sticker_file_ids=sticker_file_ids
    )

    success = result["ok"]
    error_msg = result.get("description", "")

    if success:
        print(f"[Send] OK {group.name}")
    else:
        print(f"[Send] FAILED {group.name}: {error_msg}")
        log_event("ERROR", "Send", f"Не вдалося відправити у '{group.name}': {error_msg}")

    return {
        "group_id": group.id,
        "group_name": group.name,
        "success": success,
        "error": error_msg if not success else None
    }


async def _send_to_one_group(
    semaphore,
    group,
    message,
    file_data_list,
    sticker_file_ids,
    index,
    total,
    prefer_cached: bool = True
):
    if semaphore is None:
        return await _send_to_one_group_inner(
            group, message, file_data_list, sticker_file_ids, index, total, prefer_cached
        )

    await asyncio.sleep(index * STAGGER_DELAY)
    async with semaphore:
        return await _send_to_one_group_inner(
            group, message, file_data_list, sticker_file_ids, index, total, prefer_cached
        )


async def _save_uploads(files: List[UploadFile]) -> tuple[list, str | None]:
    file_data_list = []
    temp_dir = None

    if not files:
        return file_data_list, temp_dir

    temp_dir = tempfile.mkdtemp(prefix="school_manager_send_")

    for index, file in enumerate(files):
        filename = _safe_filename(file.filename, f"file_{index}")
        temp_path = os.path.join(temp_dir, f"{index:03d}_{filename}")

        with open(temp_path, "wb") as output:
            while True:
                chunk = await file.read(FILE_READ_CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)

        item = {
            "filename": filename,
            "path": temp_path,
            "type": file.content_type,
        }
        item["kind"] = _detect_kind(item)
        file_data_list.append(item)

    return file_data_list, temp_dir


def _load_stored_files(stored_files: str) -> list:
    if not stored_files:
        return []

    try:
        items = json.loads(stored_files)
    except Exception:
        raise HTTPException(status_code=400, detail="Неправильний формат stored_files")

    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="stored_files має бути списком")

    file_data_list = []
    missing = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        storage = item.get("storage")
        stored_filename = item.get("stored_filename")
        filename = _safe_filename(item.get("filename"), f"stored_file_{index}")
        content_type = item.get("type") or item.get("content_type") or "application/octet-stream"

        try:
            path = stored_file_path(storage, stored_filename)
        except Exception:
            missing.append(filename)
            continue

        if not os.path.exists(path):
            missing.append(filename)
            continue

        data = {
            "filename": filename,
            "path": path,
            "type": content_type,
            "stored": True,
            "storage": storage,
            "stored_filename": stored_filename,
        }
        data["kind"] = _detect_kind(data)
        file_data_list.append(data)

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Файли не знайдено: {', '.join(missing)}"
        )

    return file_data_list


def _load_stickers(stickers: str) -> list:
    if not stickers:
        return []

    try:
        items = json.loads(stickers)
    except Exception:
        raise HTTPException(status_code=400, detail="Неправильний формат stickers")

    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="stickers має бути списком")

    sticker_items = []
    for item in items[:MAX_STICKERS_PER_SEND]:
        if isinstance(item, str):
            file_id = item.strip()
            if file_id:
                sticker_items.append(file_id)
        elif isinstance(item, dict):
            file_id = str(item.get("file_id") or "").strip()
            pack = str(item.get("pack_short_name") or "").strip()
            document_id = str(item.get("document_id") or item.get("id") or "").strip()
            if file_id or (pack and document_id):
                sticker_items.append({
                    "file_id": file_id,
                    "pack_short_name": pack,
                    "document_id": document_id,
                })

    return sticker_items


@router.post("/import-url")
async def import_url_file(payload: ImportUrlRequest):
    path = None
    parsed = urlparse(payload.url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Підтримуються тільки http/https посилання")

    timeout = httpx.Timeout(60.0, connect=10.0)
    headers = {"User-Agent": "SchoolManager/2.1"}

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", payload.url) as response:
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "application/octet-stream").split(";")[0]
                length = int(response.headers.get("content-length") or 0)
                if length > MAX_REMOTE_IMPORT_BYTES:
                    raise HTTPException(status_code=413, detail="Файл занадто великий для імпорту")

                header_name = _content_disposition_filename(response.headers.get("content-disposition"))
                filename = payload.filename or header_name or filename_from_url(payload.url)
                filename = _filename_with_content_type_extension(_safe_filename(filename, "imported_file"), content_type)
                stored_filename = unique_stored_name(f"pending_{filename}")
                path = import_file_path(stored_filename)
                size = 0
                digest = hashlib.sha256()

                with open(path, "wb") as output:
                    async for chunk in response.aiter_bytes(chunk_size=FILE_READ_CHUNK_SIZE):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > MAX_REMOTE_IMPORT_BYTES:
                            remove_file_quiet(path)
                            raise HTTPException(status_code=413, detail="Файл занадто великий для імпорту")
                        digest.update(chunk)
                        output.write(chunk)

                file_digest = digest.hexdigest()
                target_stored_filename = _content_addressed_import_name(filename, file_digest)
                target_path = import_file_path(target_stored_filename)
                if os.path.exists(target_path):
                    remove_file_quiet(path)
                    stored_filename = target_stored_filename
                elif matching_path := _find_matching_import_file(os.path.dirname(path), file_digest, size, path):
                    remove_file_quiet(path)
                    stored_filename = os.path.basename(matching_path)
                else:
                    os.replace(path, target_path)
                    stored_filename = target_stored_filename

    except HTTPException:
        raise
    except Exception as error:
        if path:
            remove_file_quiet(path)
        raise HTTPException(status_code=400, detail=f"Не вдалося імпортувати файл: {error}")

    return {
        "storage": "import",
        "stored_filename": stored_filename,
        "filename": filename,
        "type": content_type,
        "size": size,
    }


@router.post("/send")
async def send_message(
    group_ids: str = Form(...),
    message: str = Form(""),
    files: List[UploadFile] = File(default=[]),
    stored_files: str = Form("[]"),
    stickers: str = Form("[]"),
    db: Session = Depends(get_db)
):
    if not pyrogram_manager.is_connected:
        raise HTTPException(
            status_code=400,
            detail="Telegram не підключено. Авторизуйтесь у Налаштуваннях."
        )

    try:
        group_ids_list = json.loads(group_ids)
    except Exception:
        raise HTTPException(status_code=400, detail="Неправильний формат group_ids")

    groups_found = db.query(Group).filter(Group.id.in_(group_ids_list)).all()
    group_by_id = {group.id: group for group in groups_found}
    groups = [group_by_id[group_id] for group_id in group_ids_list if group_id in group_by_id]

    if not groups:
        raise HTTPException(status_code=404, detail="Групи не знайдено")

    file_data_list, temp_dir = await _save_uploads(files)
    file_data_list.extend(_load_stored_files(stored_files))
    sticker_file_ids = _load_stickers(stickers)
    if not message.strip() and not file_data_list and not sticker_file_ids:
        raise HTTPException(status_code=400, detail="Введіть текст, додайте файл або виберіть наліпку")

    total = len(groups)
    start_time = time.time()
    print(f"[Send] Start: {total} groups, {len(file_data_list)} files, {len(sticker_file_ids)} stickers")

    try:
        results = []

        if file_data_list:
            cache_ready = False
            next_index = 0

            for index, group in enumerate(groups):
                result = await _send_to_one_group(
                    None,
                        group,
                        message,
                        file_data_list,
                        sticker_file_ids,
                        index,
                        total,
                        prefer_cached=cache_ready
                )
                results.append(result)
                next_index = index + 1
                if result["success"]:
                    cache_ready = True
                    break

            if cache_ready and next_index < total:
                semaphore = asyncio.Semaphore(CONCURRENT_LIMIT_MEDIA)
                tasks = [
                    _send_to_one_group(
                        semaphore,
                        group,
                        message,
                        file_data_list,
                        sticker_file_ids,
                        index,
                        total,
                        prefer_cached=True
                    )
                    for index, group in enumerate(groups[next_index:], start=next_index)
                ]
                results.extend(await asyncio.gather(*tasks))
        else:
            semaphore = asyncio.Semaphore(CONCURRENT_LIMIT_TEXT)
            tasks = [
                _send_to_one_group(
                    semaphore,
                    group,
                    message,
                    None,
                    sticker_file_ids,
                    index,
                    total,
                    prefer_cached=True
                )
                for index, group in enumerate(groups)
            ]
            results = list(await asyncio.gather(*tasks))

        elapsed = round(time.time() - start_time, 2)
        success_count = sum(1 for result in results if result["success"])
        failed_count = total - success_count

        level = "INFO" if failed_count == 0 else "WARNING"
        log_event(
            level,
            "Send",
            f"Відправлено у {success_count} з {total} груп; файлів: {len(file_data_list)}; наліпок: {len(sticker_file_ids)}; час: {elapsed} с"
        )

        return {
            "message": f"Повідомлення відправлено у {success_count} з {total} груп",
            "results": results,
            "elapsed_seconds": elapsed
        }

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
