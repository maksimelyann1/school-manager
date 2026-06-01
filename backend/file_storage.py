import os
import re
import shutil
import time
import uuid
from urllib.parse import unquote, urlparse

from database import db_dir


TEMPLATE_FILES_DIR = os.path.join(db_dir, "template_files")
AUTO_MESSAGE_FILES_DIR = os.path.join(db_dir, "auto_message_files")
IMPORT_CACHE_DIR = os.path.join(db_dir, "import_cache")
FILE_READ_CHUNK_SIZE = 1024 * 1024
IMPORT_CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_REMOTE_IMPORT_BYTES = 256 * 1024 * 1024


def ensure_storage_dirs():
    os.makedirs(TEMPLATE_FILES_DIR, exist_ok=True)
    os.makedirs(AUTO_MESSAGE_FILES_DIR, exist_ok=True)
    os.makedirs(IMPORT_CACHE_DIR, exist_ok=True)


def safe_filename(filename: str | None, fallback: str = "file") -> str:
    name = os.path.basename(filename or fallback).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or fallback


def filename_from_url(url: str, fallback: str = "imported_file") -> str:
    parsed = urlparse(url)
    name = safe_filename(unquote(os.path.basename(parsed.path)), fallback)
    return name if "." in name else fallback


def unique_stored_name(filename: str) -> str:
    base = safe_filename(filename, "file")
    stem, ext = os.path.splitext(base)
    stem = stem[:80] or "file"
    ext = ext[:20]
    return f"{int(time.time())}_{uuid.uuid4().hex[:12]}_{stem}{ext}"


def _resolve_inside(directory: str, stored_filename: str) -> str:
    ensure_storage_dirs()
    base = os.path.abspath(directory)
    path = os.path.abspath(os.path.join(base, safe_filename(stored_filename)))
    if os.path.commonpath([base, path]) != base:
        raise ValueError("Invalid stored filename")
    return path


def template_file_path(stored_filename: str) -> str:
    return _resolve_inside(TEMPLATE_FILES_DIR, stored_filename)


def auto_message_file_path(stored_filename: str) -> str:
    return _resolve_inside(AUTO_MESSAGE_FILES_DIR, stored_filename)


def import_file_path(stored_filename: str) -> str:
    return _resolve_inside(IMPORT_CACHE_DIR, stored_filename)


def stored_file_path(storage: str, stored_filename: str) -> str:
    if storage == "template":
        return template_file_path(stored_filename)
    if storage == "auto":
        return auto_message_file_path(stored_filename)
    if storage == "import":
        return import_file_path(stored_filename)
    raise ValueError("Unsupported storage")


def remove_file_quiet(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


async def save_upload_to_template(upload_file, file_order: int):
    return await _save_upload_to_storage(upload_file, file_order, template_file_path)


async def save_upload_to_auto_message(upload_file, file_order: int):
    return await _save_upload_to_storage(upload_file, file_order, auto_message_file_path)


async def _save_upload_to_storage(upload_file, file_order: int, path_resolver):
    ensure_storage_dirs()
    original_filename = safe_filename(upload_file.filename, f"file_{file_order}")
    stored_filename = unique_stored_name(original_filename)
    path = path_resolver(stored_filename)
    size = 0

    with open(path, "wb") as output:
        while True:
            chunk = await upload_file.read(FILE_READ_CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            output.write(chunk)

    return {
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "content_type": upload_file.content_type or "application/octet-stream",
        "size": size,
        "file_order": file_order,
    }


def save_stored_to_template(file_item: dict, file_order: int):
    return _save_stored_to_storage(file_item, file_order, template_file_path)


def save_stored_to_auto_message(file_item: dict, file_order: int):
    return _save_stored_to_storage(file_item, file_order, auto_message_file_path)


def _save_stored_to_storage(file_item: dict, file_order: int, path_resolver):
    ensure_storage_dirs()
    storage = file_item.get("storage")
    stored_filename = file_item.get("stored_filename")
    source_path = stored_file_path(storage, stored_filename)
    if not os.path.exists(source_path):
        raise FileNotFoundError(file_item.get("filename") or stored_filename or "file")

    original_filename = safe_filename(
        file_item.get("filename") or file_item.get("original_filename"),
        f"file_{file_order}"
    )
    new_stored_filename = unique_stored_name(original_filename)
    target_path = path_resolver(new_stored_filename)
    shutil.copy2(source_path, target_path)
    size = os.path.getsize(target_path)

    return {
        "original_filename": original_filename,
        "stored_filename": new_stored_filename,
        "content_type": file_item.get("type") or file_item.get("content_type") or "application/octet-stream",
        "size": size,
        "file_order": file_order,
    }


def cleanup_cache(
    used_template_files: set[str],
    used_auto_message_files: set[str] | None = None,
    clear_import_cache: bool = False,
):
    ensure_storage_dirs()
    used_auto_message_files = used_auto_message_files or set()
    deleted_count = 0
    freed_bytes = 0
    now = time.time()

    for folder, mode in (
        (TEMPLATE_FILES_DIR, "orphans"),
        (AUTO_MESSAGE_FILES_DIR, "auto_orphans"),
        (IMPORT_CACHE_DIR, "old_imports"),
    ):
        if not os.path.exists(folder):
            continue
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            should_delete = False
            if mode == "orphans":
                should_delete = entry.name not in used_template_files
            elif mode == "auto_orphans":
                should_delete = entry.name not in used_auto_message_files
            elif clear_import_cache:
                should_delete = True
            else:
                should_delete = now - entry.stat().st_mtime > IMPORT_CACHE_TTL_SECONDS

            if should_delete:
                try:
                    size = entry.stat().st_size
                    os.remove(entry.path)
                    deleted_count += 1
                    freed_bytes += size
                except Exception:
                    pass

    return {
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
    }


def cache_status(used_template_files: set[str], used_auto_message_files: set[str] | None = None):
    ensure_storage_dirs()
    used_auto_message_files = used_auto_message_files or set()
    status = {
        "template_files_count": 0,
        "template_files_bytes": 0,
        "orphan_template_files_count": 0,
        "orphan_template_files_bytes": 0,
        "auto_message_files_count": 0,
        "auto_message_files_bytes": 0,
        "orphan_auto_message_files_count": 0,
        "orphan_auto_message_files_bytes": 0,
        "import_cache_count": 0,
        "import_cache_bytes": 0,
    }

    if os.path.exists(TEMPLATE_FILES_DIR):
        for entry in os.scandir(TEMPLATE_FILES_DIR):
            if not entry.is_file():
                continue
            size = entry.stat().st_size
            status["template_files_count"] += 1
            status["template_files_bytes"] += size
            if entry.name not in used_template_files:
                status["orphan_template_files_count"] += 1
                status["orphan_template_files_bytes"] += size

    if os.path.exists(AUTO_MESSAGE_FILES_DIR):
        for entry in os.scandir(AUTO_MESSAGE_FILES_DIR):
            if not entry.is_file():
                continue
            size = entry.stat().st_size
            status["auto_message_files_count"] += 1
            status["auto_message_files_bytes"] += size
            if entry.name not in used_auto_message_files:
                status["orphan_auto_message_files_count"] += 1
                status["orphan_auto_message_files_bytes"] += size

    if os.path.exists(IMPORT_CACHE_DIR):
        for entry in os.scandir(IMPORT_CACHE_DIR):
            if not entry.is_file():
                continue
            status["import_cache_count"] += 1
            status["import_cache_bytes"] += entry.stat().st_size

    status["total_bytes"] = (
        status["template_files_bytes"]
        + status["auto_message_files_bytes"]
        + status["import_cache_bytes"]
    )
    status["total_mb"] = round(status["total_bytes"] / 1024 / 1024, 2)
    return status


def clear_directory(path: str):
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
