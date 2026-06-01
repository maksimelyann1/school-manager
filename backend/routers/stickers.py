import asyncio
import gzip
import hashlib
import json
import os
import shutil
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pyrogram import raw
from pyrogram.errors import FloodWait, RPCError
from pyrogram.file_id import FileId, FileType, ThumbnailSource

from app_paths import get_runtime_data_dir
from database import SessionLocal
from logger import log_event
from models import BotSettings
from pyrogram_client import pyrogram_manager
from telegram_credentials import get_effective_credentials

router = APIRouter(prefix="/stickers", tags=["Наліпки"])

STICKER_CACHE_DIR = os.path.join(get_runtime_data_dir(), "sticker_cache")
METADATA_CACHE_DIR = os.path.join(STICKER_CACHE_DIR, "metadata")
THUMB_CACHE_DIR = os.path.join(STICKER_CACHE_DIR, "thumbs")
ANIMATION_CACHE_DIR = os.path.join(STICKER_CACHE_DIR, "animations")

METADATA_CACHE_TTL_SECONDS = 24 * 60 * 60
STICKER_FILE_CACHE_SECONDS = 7 * 24 * 60 * 60
METADATA_CACHE_SCHEMA_VERSION = 2
STICKER_THUMB_DOWNLOAD_TIMEOUT_SECONDS = 18
STICKER_ANIMATION_DOWNLOAD_TIMEOUT_SECONDS = 28
STICKER_WARMUP_INITIAL_DELAY_SECONDS = 20
STICKER_WARMUP_PACK_LIMIT = 12
STICKER_WARMUP_THUMBS_PER_PACK = 18
STICKER_WARMUP_TOTAL_THUMB_LIMIT = 180
STICKER_WARMUP_CONCURRENCY = 2
STICKER_WARMUP_MAX_ERRORS = 8
STICKER_WARMUP_USER_IDLE_SECONDS = 1.0
STICKER_WARMUP_BETWEEN_DOWNLOADS_SECONDS = 0.5
STICKER_MIME_EXTENSIONS = {
    "application/x-tgsticker": ".json",
    "video/webm": ".webm",
    "image/webp": ".webp",
}

_packs_cache: dict = {"expires_at": 0.0, "data": None}
_pack_cache: dict[str, dict] = {}
_file_locks: dict[str, asyncio.Lock] = {}
_thumb_download_semaphore = asyncio.Semaphore(2)
_animation_download_semaphore = asyncio.Semaphore(1)
_warmup_task: asyncio.Task | None = None
_warmup_generation = 0
_active_foreground_media_requests = 0
_media_flood_wait_until = 0.0
_warmup_state: dict = {
    "running": False,
    "reason": "",
    "started_at": None,
    "finished_at": None,
    "current_pack": "",
    "packs_seen": 0,
    "thumbs_cached": 0,
    "thumbs_skipped": 0,
    "errors": 0,
    "last_error": "",
}


def _wall_now() -> float:
    return time.time()


def _ensure_cache_dirs():
    for directory in (STICKER_CACHE_DIR, METADATA_CACHE_DIR, THUMB_CACHE_DIR, ANIMATION_CACHE_DIR):
        os.makedirs(directory, exist_ok=True)


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_cache_path(name: str) -> str:
    _ensure_cache_dirs()
    return os.path.join(METADATA_CACHE_DIR, f"{_hash_key(name)}.json")


def _read_json_cache(path: str):
    try:
        if not os.path.exists(path):
            return None
        if _wall_now() - os.path.getmtime(path) > METADATA_CACHE_TTL_SECONDS:
            return None
        with open(path, "r", encoding="utf-8") as source:
            data = json.load(source)
        if data.get("_schema_version") != METADATA_CACHE_SCHEMA_VERSION:
            return None
        data.pop("_schema_version", None)
        return data
    except Exception:
        return None


def _write_json_cache(path: str, data: dict):
    _ensure_cache_dirs()
    tmp_path = f"{path}.{os.getpid()}.tmp"
    payload = {**data, "_schema_version": METADATA_CACHE_SCHEMA_VERSION}
    with open(tmp_path, "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, path)


def _file_lock(path: str) -> asyncio.Lock:
    lock = _file_locks.get(path)
    if lock is None:
        lock = asyncio.Lock()
        _file_locks[path] = lock
    return lock


def _cache_path(kind: str, cache_key: str, mime_type: str) -> str:
    _ensure_cache_dirs()
    directory = THUMB_CACHE_DIR if kind == "thumb" else ANIMATION_CACHE_DIR
    extension = ".webp" if kind == "thumb" else STICKER_MIME_EXTENSIONS.get(mime_type, ".webp")
    return os.path.join(directory, f"{_hash_key(f'{kind}:{cache_key}:{mime_type}')}{extension}")


def _media_cached(kind: str, cache_key: str, mime_type: str) -> bool:
    return _valid_cache_file(_cache_path(kind, cache_key, mime_type))


def _valid_cache_file(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _remove_broken_cache_file(path: str):
    try:
        if os.path.exists(path) and not _valid_cache_file(path):
            os.remove(path)
    except OSError:
        pass


def _thumb_cache_key(sticker: dict) -> str:
    pack = str(sticker.get("pack_short_name") or "").strip()
    document_id = str(sticker.get("document_id") or sticker.get("id") or "").strip()
    if pack and document_id:
        return f"{pack}:{document_id}:thumb"
    return str(sticker.get("thumb_file_id") or sticker.get("file_id") or "").strip()


def _media_url(endpoint: str, file_id: str, mime_type: str, pack_short_name: str | None, document_id: str) -> str:
    if not file_id:
        return ""
    return (
        f"/api/stickers/{endpoint}?file_id={quote(file_id, safe='')}"
        f"&mime_type={quote(mime_type, safe='')}"
        f"&pack={quote(pack_short_name or '', safe='')}"
        f"&document_id={quote(str(document_id), safe='')}"
    )


async def _client_or_error(allow_reconnect: bool = True):
    client = pyrogram_manager.client
    if client and pyrogram_manager.is_connected:
        return client

    if not allow_reconnect:
        if pyrogram_manager.has_session():
            raise HTTPException(status_code=503, detail="Telegram підключається. Спробуйте ще раз.")
        raise HTTPException(status_code=400, detail="Telegram не підключено")

    if pyrogram_manager.manually_disconnected or not pyrogram_manager.has_session():
        raise HTTPException(status_code=400, detail="Telegram не підключено")

    db = SessionLocal()
    try:
        settings = db.query(BotSettings).first()
        credentials = get_effective_credentials(settings)
    except Exception as error:
        log_event("WARNING", "Stickers", f"Не вдалося відновити Telegram-сесію для наліпок: {error}")
        raise HTTPException(status_code=400, detail="Telegram не підключено") from error
    finally:
        db.close()

    try:
        connected = await pyrogram_manager.connect_with_session(credentials.api_id, credentials.api_hash)
    except Exception as error:
        log_event("WARNING", "Stickers", f"Помилка відновлення Telegram-сесії для наліпок: {error}")
        connected = False

    if not connected or not pyrogram_manager.client:
        raise HTTPException(status_code=400, detail="Telegram не підключено")
    return pyrogram_manager.client


def _attrs_map(document):
    return {type(attribute): attribute for attribute in getattr(document, "attributes", [])}


def _sticker_file_id(document) -> str:
    return FileId(
        file_type=FileType.STICKER,
        dc_id=document.dc_id,
        media_id=document.id,
        access_hash=document.access_hash,
        file_reference=document.file_reference,
    ).encode()


def _thumb_file_id(document) -> str:
    photo_sizes = [
        thumb for thumb in (getattr(document, "thumbs", None) or [])
        if isinstance(thumb, raw.types.PhotoSize)
    ]
    if not photo_sizes:
        return ""

    thumb = max(photo_sizes, key=lambda item: getattr(item, "size", 0) or 0)
    return FileId(
        file_type=FileType.THUMBNAIL,
        dc_id=document.dc_id,
        media_id=document.id,
        access_hash=document.access_hash,
        file_reference=document.file_reference,
        thumbnail_file_type=FileType.THUMBNAIL,
        thumbnail_source=ThumbnailSource.THUMBNAIL,
        thumbnail_size=thumb.type,
        volume_id=0,
        local_id=0,
    ).encode()


def _sticker_item(document, pack_short_name: str | None = None) -> dict | None:
    attrs = _attrs_map(document)
    sticker_attr = attrs.get(raw.types.DocumentAttributeSticker) or attrs.get(raw.types.DocumentAttributeCustomEmoji)
    if not sticker_attr:
        return None

    image_size = attrs.get(raw.types.DocumentAttributeImageSize)
    video_size = attrs.get(raw.types.DocumentAttributeVideo)
    filename_attr = attrs.get(raw.types.DocumentAttributeFilename)
    mime_type = document.mime_type or "image/webp"
    document_id = str(document.id)
    file_id = _sticker_file_id(document)
    thumb_file_id = _thumb_file_id(document)
    thumb_url = _media_url("thumb", thumb_file_id, "image/webp", pack_short_name, document_id)
    animation_url = _media_url("animation", file_id, mime_type, pack_short_name, document_id)

    return {
        "id": document_id,
        "document_id": document_id,
        "file_id": file_id,
        "thumb_file_id": thumb_file_id,
        "emoji": getattr(sticker_attr, "alt", "") or "",
        "mime_type": mime_type,
        "is_animated": mime_type == "application/x-tgsticker",
        "is_video": mime_type == "video/webm",
        "width": getattr(image_size, "w", None) or getattr(video_size, "w", None) or 512,
        "height": getattr(image_size, "h", None) or getattr(video_size, "h", None) or 512,
        "file_size": getattr(document, "size", 0) or 0,
        "file_name": getattr(filename_attr, "file_name", None) or document_id,
        "pack_short_name": pack_short_name,
        "thumb_url": thumb_url,
        "animation_url": animation_url,
        "preview_url": thumb_url or animation_url,
    }


def _pack_item(sticker_set) -> dict:
    return {
        "id": str(sticker_set.id),
        "access_hash": str(sticker_set.access_hash),
        "title": sticker_set.title,
        "short_name": sticker_set.short_name,
        "count": sticker_set.count,
        "animated": bool(getattr(sticker_set, "animated", False)),
        "videos": bool(getattr(sticker_set, "videos", False)),
        "emojis": bool(getattr(sticker_set, "emojis", False)),
    }


def _pack_response(result) -> dict:
    stickers = [
        item
        for document in getattr(result, "documents", [])
        if (item := _sticker_item(document, result.set.short_name))
    ]
    return {
        "pack": _pack_item(result.set),
        "stickers": stickers,
    }


async def _load_pack_from_telegram(short_name: str) -> dict:
    client = await _client_or_error()
    result = await client.invoke(
        raw.functions.messages.GetStickerSet(
            stickerset=raw.types.InputStickerSetShortName(short_name=short_name),
            hash=0,
        )
    )
    data = _pack_response(result)
    _pack_cache[short_name] = {
        "expires_at": _wall_now() + METADATA_CACHE_TTL_SECONDS,
        "data": data,
    }
    _write_json_cache(_json_cache_path(f"pack:{short_name}"), data)
    return data


async def _fresh_sticker_item(pack_short_name: str, document_id: str) -> dict | None:
    if not pack_short_name or not document_id:
        return None

    try:
        data = await _load_pack_from_telegram(pack_short_name)
    except Exception as error:
        log_event("WARNING", "Stickers", f"Не вдалося оновити file_reference для наліпки: {error}")
        return None

    for item in data.get("stickers", []):
        if str(item.get("document_id") or item.get("id")) == str(document_id):
            return item
    return None


async def resolve_sticker_file_id(sticker: dict | str) -> str:
    if isinstance(sticker, str):
        return sticker.strip()

    file_id = str(sticker.get("file_id") or "").strip()
    pack = str(sticker.get("pack_short_name") or "").strip()
    document_id = str(sticker.get("document_id") or sticker.get("id") or "").strip()
    if file_id:
        return file_id
    if not pack or not document_id:
        return ""

    fresh_item = await _fresh_sticker_item(pack, document_id)
    return str((fresh_item or {}).get("file_id") or "")


async def refresh_sticker_file_id(pack_short_name: str, document_id: str) -> str:
    fresh_item = await _fresh_sticker_item(pack_short_name, document_id)
    return str((fresh_item or {}).get("file_id") or "")


async def _download_cached_media(
    *,
    file_id: str,
    mime_type: str,
    kind: str,
    cache_key: str,
    transform_tgs: bool,
) -> str:
    global _media_flood_wait_until
    path = _cache_path(kind, cache_key, mime_type)
    _remove_broken_cache_file(path)
    if _valid_cache_file(path):
        return path

    flood_wait_left = int(max(0, _media_flood_wait_until - _wall_now()))
    if flood_wait_left > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Telegram тимчасово обмежив завантаження наліпок. Спробуйте через {flood_wait_left} с.",
        )

    async with _file_lock(path):
        _remove_broken_cache_file(path)
        if _valid_cache_file(path):
            return path

        flood_wait_left = int(max(0, _media_flood_wait_until - _wall_now()))
        if flood_wait_left > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Telegram тимчасово обмежив завантаження наліпок. Спробуйте через {flood_wait_left} с.",
            )

        client = await _client_or_error(allow_reconnect=False)
        semaphore = _thumb_download_semaphore if kind == "thumb" else _animation_download_semaphore
        timeout = STICKER_THUMB_DOWNLOAD_TIMEOUT_SECONDS if kind == "thumb" else STICKER_ANIMATION_DOWNLOAD_TIMEOUT_SECONDS
        try:
            async with semaphore:
                media_file = await asyncio.wait_for(
                    client.download_media(file_id, in_memory=True),
                    timeout=timeout,
                )
        except asyncio.TimeoutError as error:
            log_event("WARNING", "Stickers", f"Telegram довго не віддає файл наліпки ({kind})")
            raise HTTPException(status_code=504, detail="Telegram довго не віддає файл наліпки") from error
        except FloodWait as error:
            wait_seconds = int(getattr(error, "value", 60) or 60)
            _media_flood_wait_until = max(_media_flood_wait_until, _wall_now() + wait_seconds)
            log_event("WARNING", "Stickers", f"Telegram FloodWait for sticker media: {wait_seconds} seconds")
            raise HTTPException(
                status_code=429,
                detail=f"Telegram тимчасово обмежив завантаження наліпок. Спробуйте через {wait_seconds} с.",
            ) from error
        except RPCError as error:
            log_event("WARNING", "Stickers", f"Telegram не віддав файл наліпки: {error}")
            raise HTTPException(status_code=404, detail="Не вдалося завантажити наліпку") from error
        except Exception as error:
            log_event("WARNING", "Stickers", f"Помилка завантаження файлу наліпки: {error}")
            raise HTTPException(status_code=404, detail="Не вдалося завантажити наліпку") from error

        if not media_file:
            raise HTTPException(status_code=404, detail="Не вдалося завантажити наліпку")

        data = bytes(media_file.getbuffer())
        if not data:
            _remove_broken_cache_file(path)
            raise HTTPException(status_code=404, detail="Telegram повернув порожній файл наліпки")

        if transform_tgs and mime_type == "application/x-tgsticker":
            try:
                data = gzip.decompress(data)
            except OSError:
                pass

        tmp_path = f"{path}.{os.getpid()}.{id(asyncio.current_task())}.tmp"
        with open(tmp_path, "wb") as output:
            output.write(data)
        os.replace(tmp_path, path)
        return path


async def _download_sticker_preview(file_id: str, mime_type: str, cache_key: str | None = None) -> str:
    return await _download_cached_media(
        file_id=file_id,
        mime_type=mime_type,
        kind="animation",
        cache_key=cache_key or file_id,
        transform_tgs=True,
    )


async def _wait_for_user_media_idle():
    while _active_foreground_media_requests > 0:
        await asyncio.sleep(STICKER_WARMUP_USER_IDLE_SECONDS)


async def _warmup_sticker_thumb(sticker: dict) -> bool:
    thumb_file_id = str(sticker.get("thumb_file_id") or "").strip()
    if not thumb_file_id:
        return False

    cache_key = _thumb_cache_key(sticker)
    if not cache_key or _media_cached("thumb", cache_key, "image/webp"):
        return False

    await _wait_for_user_media_idle()
    if not pyrogram_manager.is_connected:
        return False

    await _download_cached_media(
        file_id=thumb_file_id,
        mime_type="image/webp",
        kind="thumb",
        cache_key=cache_key,
        transform_tgs=False,
    )
    return True


async def _run_sticker_cache_warmup(reason: str, generation: int):
    _warmup_state.update({
        "running": True,
        "reason": reason,
        "started_at": _wall_now(),
        "finished_at": None,
        "current_pack": "",
        "packs_seen": 0,
        "thumbs_cached": 0,
        "thumbs_skipped": 0,
        "errors": 0,
        "last_error": "",
    })

    try:
        await asyncio.sleep(STICKER_WARMUP_INITIAL_DELAY_SECONDS)
        if generation != _warmup_generation:
            return
        if not pyrogram_manager.is_connected:
            return

        packs_data = await get_sticker_packs()
        packs = [
            item for item in (packs_data.get("packs") or [])
            if str(item.get("short_name") or "").strip()
        ]

        total_cached = 0
        for pack in packs[:STICKER_WARMUP_PACK_LIMIT]:
            if generation != _warmup_generation:
                return
            if total_cached >= STICKER_WARMUP_TOTAL_THUMB_LIMIT:
                break
            if not pyrogram_manager.is_connected:
                break

            short_name = str(pack.get("short_name") or "").strip()
            _warmup_state["current_pack"] = short_name
            _warmup_state["packs_seen"] += 1

            try:
                pack_data = await get_sticker_pack(short_name)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _warmup_state["errors"] += 1
                _warmup_state["last_error"] = str(error)
                log_event("WARNING", "Stickers", f"Sticker warmup skipped pack {short_name}: {error}")
                if _warmup_state["errors"] >= STICKER_WARMUP_MAX_ERRORS:
                    return
                continue

            stickers = [
                item for item in (pack_data.get("stickers") or [])
                if str(item.get("thumb_file_id") or "").strip()
            ][:STICKER_WARMUP_THUMBS_PER_PACK]

            candidates = []
            for sticker in stickers:
                if total_cached >= STICKER_WARMUP_TOTAL_THUMB_LIMIT:
                    break
                cache_key = _thumb_cache_key(sticker)
                if not cache_key or _media_cached("thumb", cache_key, "image/webp"):
                    _warmup_state["thumbs_skipped"] += 1
                    continue
                candidates.append(sticker)

            for index in range(0, len(candidates), STICKER_WARMUP_CONCURRENCY):
                if generation != _warmup_generation:
                    return
                if total_cached >= STICKER_WARMUP_TOTAL_THUMB_LIMIT:
                    break
                remaining = STICKER_WARMUP_TOTAL_THUMB_LIMIT - total_cached
                batch_size = min(STICKER_WARMUP_CONCURRENCY, remaining)
                batch = candidates[index:index + batch_size]
                results = await asyncio.gather(
                    *[_warmup_sticker_thumb(sticker) for sticker in batch],
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    if isinstance(result, HTTPException) and result.status_code == 429:
                        _warmup_state["errors"] += 1
                        _warmup_state["last_error"] = str(result.detail)
                        log_event("WARNING", "Stickers", f"Sticker warmup paused: {result.detail}")
                        return
                    if isinstance(result, Exception):
                        _warmup_state["errors"] += 1
                        detail = getattr(result, "detail", None) or str(result)
                        _warmup_state["last_error"] = str(detail)
                        log_event("WARNING", "Stickers", f"Sticker warmup thumb failed: {detail}")
                        if _warmup_state["errors"] >= STICKER_WARMUP_MAX_ERRORS:
                            return
                        continue
                    if result:
                        total_cached += 1
                        _warmup_state["thumbs_cached"] += 1
                await asyncio.sleep(STICKER_WARMUP_BETWEEN_DOWNLOADS_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        _warmup_state["errors"] += 1
        _warmup_state["last_error"] = str(error)
        log_event("WARNING", "Stickers", f"Sticker warmup failed: {error}")
    finally:
        if generation == _warmup_generation:
            _warmup_state["running"] = False
            _warmup_state["current_pack"] = ""
            _warmup_state["finished_at"] = _wall_now()


def schedule_sticker_cache_warmup(reason: str = "startup", force: bool = False) -> bool:
    global _warmup_generation, _warmup_task
    if not pyrogram_manager.is_connected:
        return False

    if _warmup_task and not _warmup_task.done():
        if not force:
            return False
        _warmup_task.cancel()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    _warmup_generation += 1
    _warmup_task = loop.create_task(_run_sticker_cache_warmup(reason, _warmup_generation))
    return True


def cancel_sticker_cache_warmup():
    global _warmup_generation, _warmup_task
    _warmup_generation += 1
    if _warmup_task and not _warmup_task.done():
        _warmup_task.cancel()
    _warmup_task = None
    _warmup_state["running"] = False
    _warmup_state["current_pack"] = ""


def sticker_warmup_status() -> dict:
    task_running = bool(_warmup_task and not _warmup_task.done())
    return {
        **_warmup_state,
        "running": bool(_warmup_state.get("running") or task_running),
        "task_running": task_running,
        "foreground_media_requests": _active_foreground_media_requests,
        "media_flood_wait_seconds": int(max(0, _media_flood_wait_until - _wall_now())),
        "pack_limit": STICKER_WARMUP_PACK_LIMIT,
        "initial_delay_seconds": STICKER_WARMUP_INITIAL_DELAY_SECONDS,
        "thumbs_per_pack": STICKER_WARMUP_THUMBS_PER_PACK,
        "total_thumb_limit": STICKER_WARMUP_TOTAL_THUMB_LIMIT,
        "max_errors": STICKER_WARMUP_MAX_ERRORS,
        "warmup_concurrency": STICKER_WARMUP_CONCURRENCY,
        "thumb_download_concurrency": 2,
    }


def clear_sticker_cache() -> dict:
    cancel_sticker_cache_warmup()
    deleted_count = 0
    freed_bytes = 0
    if os.path.isdir(STICKER_CACHE_DIR):
        for current_root, _dirs, files in os.walk(STICKER_CACHE_DIR):
            for filename in files:
                path = os.path.join(current_root, filename)
                try:
                    freed_bytes += os.path.getsize(path)
                    deleted_count += 1
                except OSError:
                    pass
        shutil.rmtree(STICKER_CACHE_DIR, ignore_errors=True)

    _packs_cache["data"] = None
    _packs_cache["expires_at"] = 0.0
    _pack_cache.clear()
    _file_locks.clear()
    _ensure_cache_dirs()
    return {
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
    }


def sticker_cache_status() -> dict:
    total_bytes = 0
    file_count = 0
    for current_root, _dirs, files in os.walk(STICKER_CACHE_DIR) if os.path.isdir(STICKER_CACHE_DIR) else []:
        for filename in files:
            path = os.path.join(current_root, filename)
            try:
                total_bytes += os.path.getsize(path)
                file_count += 1
            except OSError:
                pass
    return {
        "sticker_cache_count": file_count,
        "sticker_cache_bytes": total_bytes,
    }


@router.get("/packs")
async def get_sticker_packs():
    cached = _packs_cache.get("data")
    if cached is not None and _packs_cache.get("expires_at", 0.0) > _wall_now():
        return cached

    cache_path = _json_cache_path("packs")
    disk_cached = _read_json_cache(cache_path)
    if disk_cached is not None:
        _packs_cache["data"] = disk_cached
        _packs_cache["expires_at"] = _wall_now() + METADATA_CACHE_TTL_SECONDS
        return disk_cached

    client = await _client_or_error()
    try:
        result = await client.invoke(raw.functions.messages.GetAllStickers(hash=0))
    except RPCError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        log_event("ERROR", "Stickers", f"Не вдалося отримати набори наліпок: {error}")
        raise HTTPException(status_code=500, detail="Не вдалося отримати набори наліпок") from error

    if isinstance(result, raw.types.messages.AllStickersNotModified):
        data = {"packs": []}
    else:
        data = {"packs": [_pack_item(sticker_set) for sticker_set in getattr(result, "sets", [])]}

    _packs_cache["data"] = data
    _packs_cache["expires_at"] = _wall_now() + METADATA_CACHE_TTL_SECONDS
    _write_json_cache(cache_path, data)
    return data


@router.get("/packs/{short_name}")
async def get_sticker_pack(short_name: str):
    cached = _pack_cache.get(short_name)
    if cached and cached.get("expires_at", 0.0) > _wall_now():
        return cached["data"]

    cache_path = _json_cache_path(f"pack:{short_name}")
    disk_cached = _read_json_cache(cache_path)
    if disk_cached is not None:
        _pack_cache[short_name] = {
            "expires_at": _wall_now() + METADATA_CACHE_TTL_SECONDS,
            "data": disk_cached,
        }
        return disk_cached

    try:
        return await _load_pack_from_telegram(short_name)
    except RPCError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        log_event("ERROR", "Stickers", f"Не вдалося отримати набір наліпок {short_name}: {error}")
        raise HTTPException(status_code=500, detail="Не вдалося отримати набір наліпок") from error


@router.get("/warmup")
async def get_sticker_warmup_status():
    return sticker_warmup_status()


@router.post("/warmup")
async def start_sticker_warmup():
    queued = schedule_sticker_cache_warmup(reason="manual", force=True)
    return {"queued": queued, **sticker_warmup_status()}


@router.get("/thumb")
async def get_sticker_thumb(
    file_id: str = Query(...),
    mime_type: str = Query("image/webp"),
    pack: str = Query(""),
    document_id: str = Query(""),
):
    global _active_foreground_media_requests
    _active_foreground_media_requests += 1
    try:
        cache_key = f"{pack}:{document_id}:thumb" if pack and document_id else file_id
        try:
            path = await _download_cached_media(
                file_id=file_id,
                mime_type="image/webp",
                kind="thumb",
                cache_key=cache_key,
                transform_tgs=False,
            )
        except HTTPException as error:
            if error.status_code != 404:
                raise
            fresh_item = await _fresh_sticker_item(pack, document_id)
            thumb_file_id = str((fresh_item or {}).get("thumb_file_id") or "")
            if not thumb_file_id:
                raise
            path = await _download_cached_media(
                file_id=thumb_file_id,
                mime_type="image/webp",
                kind="thumb",
                cache_key=cache_key,
                transform_tgs=False,
            )

        return FileResponse(
            path,
            media_type="image/webp",
            headers={"Cache-Control": f"public, max-age={STICKER_FILE_CACHE_SECONDS}"},
        )
    finally:
        _active_foreground_media_requests = max(0, _active_foreground_media_requests - 1)


@router.get("/animation")
async def get_sticker_animation(
    file_id: str = Query(...),
    mime_type: str = Query("image/webp"),
    pack: str = Query(""),
    document_id: str = Query(""),
):
    global _active_foreground_media_requests
    _active_foreground_media_requests += 1
    try:
        cache_key = f"{pack}:{document_id}:animation" if pack and document_id else file_id
        try:
            path = await _download_cached_media(
                file_id=file_id,
                mime_type=mime_type,
                kind="animation",
                cache_key=cache_key,
                transform_tgs=True,
            )
        except HTTPException as error:
            if error.status_code != 404:
                raise
            fresh_item = await _fresh_sticker_item(pack, document_id)
            if not fresh_item:
                raise
            mime_type = fresh_item["mime_type"]
            path = await _download_cached_media(
                file_id=fresh_item["file_id"],
                mime_type=mime_type,
                kind="animation",
                cache_key=cache_key,
                transform_tgs=True,
            )

        headers = {"Cache-Control": f"public, max-age={STICKER_FILE_CACHE_SECONDS}"}
        if mime_type == "application/x-tgsticker":
            return FileResponse(path, media_type="application/json", headers=headers)
        if mime_type == "video/webm":
            return FileResponse(path, media_type="video/webm", headers=headers)
        if mime_type == "image/webp":
            return FileResponse(path, media_type="image/webp", headers=headers)
        return FileResponse(path, media_type=mime_type, headers=headers)
    finally:
        _active_foreground_media_requests = max(0, _active_foreground_media_requests - 1)


@router.get("/file")
async def get_sticker_file(
    file_id: str = Query(...),
    mime_type: str = Query("image/webp"),
    pack: str = Query(""),
    document_id: str = Query(""),
):
    return await get_sticker_animation(
        file_id=file_id,
        mime_type=mime_type,
        pack=pack,
        document_id=document_id,
    )
