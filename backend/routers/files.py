import hashlib
import mimetypes
import os
import subprocess
import sys

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from file_storage import (
    FILE_READ_CHUNK_SIZE,
    import_file_path,
    remove_file_quiet,
    safe_filename,
    stored_file_path,
    unique_stored_name,
)


router = APIRouter(prefix="/files", tags=["Файли"])


class StoredFileRequest(BaseModel):
    storage: str
    stored_filename: str


def _resolve_stored_file(storage: str, stored_filename: str) -> str:
    try:
        path = stored_file_path(storage, stored_filename)
    except Exception:
        raise HTTPException(status_code=400, detail="Неправильний файл")

    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Файл не знайдено")

    return path


def _open_path(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Не вдалося відкрити файл: {error}")


def _history_cache_filename(filename: str, digest: str) -> str:
    stem, ext = os.path.splitext(filename)
    stem = safe_filename(stem, "history_file")[:80]
    ext = ext[:20]
    return f"history_{digest[:16]}_{stem}{ext}"


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(FILE_READ_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _find_matching_cached_file(folder: str, expected_digest: str, expected_size: int, exclude_path: str) -> str | None:
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


@router.get("/preview")
def preview_file(storage: str, stored_filename: str):
    path = _resolve_stored_file(storage, stored_filename)
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=os.path.basename(path),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/open")
def open_file(payload: StoredFileRequest):
    path = _resolve_stored_file(payload.storage, payload.stored_filename)
    _open_path(path)
    return {"ok": True}


@router.post("/open-upload")
async def open_uploaded_file(file: UploadFile = File(...)):
    filename = safe_filename(file.filename, "history_file")
    temp_path = import_file_path(unique_stored_name(f"pending_{filename}"))
    path_to_open = temp_path

    try:
        digest = hashlib.sha256()
        size = 0
        with open(temp_path, "wb") as output:
            while True:
                chunk = await file.read(FILE_READ_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)

        file_digest = digest.hexdigest()
        cached_path = import_file_path(_history_cache_filename(filename, file_digest))
        if os.path.exists(cached_path):
            remove_file_quiet(temp_path)
            path_to_open = cached_path
            reused = True
        elif matching_path := _find_matching_cached_file(os.path.dirname(temp_path), file_digest, size, temp_path):
            remove_file_quiet(temp_path)
            path_to_open = matching_path
            reused = True
        else:
            os.replace(temp_path, cached_path)
            path_to_open = cached_path
            reused = False

        _open_path(path_to_open)
    except HTTPException:
        if path_to_open == temp_path:
            remove_file_quiet(temp_path)
        raise
    except Exception as error:
        if path_to_open == temp_path:
            remove_file_quiet(temp_path)
        raise HTTPException(status_code=500, detail=f"Не вдалося відкрити файл: {error}")

    return {"ok": True, "reused": reused}
