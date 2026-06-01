import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app_paths import get_runtime_data_dir
from database import db_path, SessionLocal
from file_storage import cache_status, cleanup_cache
from logger import log_event
from models import AppLog, AutoMessage, AutoMessageFile, BotSettings, Category, Group, ParentReportLesson, ParentReportRun, Template, TemplateFile
from platform_autostart import autostart_status, read_autostart_value, write_autostart_value
from routers.stickers import clear_sticker_cache, sticker_cache_status
from system_notifications import system_notifications_supported
from version_config import APP_VERSION, UPDATE_CHECK_URL

router = APIRouter(prefix="/system", tags=["Система"])
START_IN_TRAY_ARG = "--start-in-tray"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AutostartRequest(BaseModel):
    enabled: bool


class NotificationsRequest(BaseModel):
    enabled: bool


class UpdateDownloadRequest(BaseModel):
    auto_install: bool = True

# Глобальний стан завантаження оновлення
_update_state = {
    "status": "idle",        # idle | checking | downloading | done | installing | error
    "progress": 0,           # 0-100
    "error": None,
    "download_url": None,
    "file_path": None,
    "latest_version": None,
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "auto_install": True,
    "platform": None,
    "file_name": None,
    "can_auto_install": True,
    "requires_manual_install": False,
}
_update_state_lock = threading.Lock()
UPDATE_NOTICE_FILENAME = "update_notice.json"
UPDATE_PACKAGE_FILENAMES = {
    "windows": "SchoolManager_Update_Setup.exe",
    "macos": "SchoolManager_Update.dmg",
}
INNO_SILENT_ARGS = [
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
]


def _update_notice_path() -> str:
    return os.path.join(get_runtime_data_dir(), UPDATE_NOTICE_FILENAME)


def _set_update_state(**kwargs):
    with _update_state_lock:
        _update_state.update(kwargs)


def _get_update_state():
    with _update_state_lock:
        return _update_state.copy()


def _write_update_notice(target_version: str | None):
    if not target_version:
        return
    try:
        os.makedirs(get_runtime_data_dir(), exist_ok=True)
        with open(_update_notice_path(), "w", encoding="utf-8") as notice_file:
            json.dump(
                {
                    "target_version": target_version,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
                notice_file,
                ensure_ascii=False,
            )
    except Exception as error:
        log_event("WARNING", "Update", f"Не вдалося зберегти маркер оновлення: {error}")


def _ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _write_visual_updater_script(installer_path: str, argument_line: str, latest_version: str | None) -> str:
    script_path = os.path.join(get_runtime_data_dir(), "SchoolManager_Update_Window.ps1")
    version_label = latest_version or "нову версію"
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$InstallerPath = {_ps_literal(installer_path)}
$ArgumentLine = {_ps_literal(argument_line)}
$VersionLabel = {_ps_literal(version_label)}

[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'School Manager Update'
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'None'
$form.Width = 512
$form.Height = 282
$form.BackColor = [System.Drawing.Color]::FromArgb(30, 41, 59)
$form.TopMost = $true

$panel = New-Object System.Windows.Forms.Panel
$panel.Left = 0
$panel.Top = 0
$panel.Width = 512
$panel.Height = 282
$panel.BackColor = [System.Drawing.Color]::FromArgb(30, 41, 59)
$panel.Dock = 'Fill'
$form.Controls.Add($panel)

$accent = New-Object System.Windows.Forms.Panel
$accent.Left = 0
$accent.Top = 0
$accent.Width = 512
$accent.Height = 4
$accent.BackColor = [System.Drawing.Color]::FromArgb(99, 102, 241)
$panel.Controls.Add($accent)

$title = New-Object System.Windows.Forms.Label
$title.Left = 34
$title.Top = 34
$title.Width = 445
$title.Height = 34
$title.Text = 'Встановлюємо оновлення'
$title.ForeColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$title.Font = New-Object System.Drawing.Font('Segoe UI', 18, [System.Drawing.FontStyle]::Bold)
$panel.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Left = 36
$subtitle.Top = 78
$subtitle.Width = 440
$subtitle.Height = 44
$subtitle.Text = "School Manager оновлюється до версії $VersionLabel. Не вимикайте комп'ютер і не запускайте програму вручну."
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(203, 213, 225)
$subtitle.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$panel.Controls.Add($subtitle)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Left = 36
$progress.Top = 148
$progress.Width = 440
$progress.Height = 12
$progress.Style = 'Marquee'
$progress.MarqueeAnimationSpeed = 32
$panel.Controls.Add($progress)

$status = New-Object System.Windows.Forms.Label
$status.Left = 36
$status.Top = 178
$status.Width = 440
$status.Height = 28
$status.Text = 'Готуємо встановлення...'
$status.ForeColor = [System.Drawing.Color]::FromArgb(153, 246, 228)
$status.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$panel.Controls.Add($status)

$note = New-Object System.Windows.Forms.Label
$note.Left = 36
$note.Top = 222
$note.Width = 440
$note.Height = 30
$note.Text = 'Якщо Windows запитає дозвіл, підтвердьте його. Після завершення програма відкриється автоматично.'
$note.ForeColor = [System.Drawing.Color]::FromArgb(148, 163, 184)
$note.Font = New-Object System.Drawing.Font('Segoe UI', 8.5)
$panel.Controls.Add($note)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Left = 396
$closeButton.Top = 226
$closeButton.Width = 82
$closeButton.Height = 32
$closeButton.Text = 'Закрити'
$closeButton.Visible = $false
$closeButton.FlatStyle = 'Flat'
$closeButton.BackColor = [System.Drawing.Color]::FromArgb(51, 65, 85)
$closeButton.ForeColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$closeButton.Add_Click({{ $form.Close() }})
$panel.Controls.Add($closeButton)

$script:installerProcess = $null
$script:started = $false
$script:dots = 0

function Set-Failed([string] $Message) {{
    $progress.Visible = $false
    $status.ForeColor = [System.Drawing.Color]::FromArgb(254, 202, 202)
    $status.Text = $Message
    $note.Text = 'Оновлення не було встановлено. Можна закрити це вікно і спробувати ще раз з програми.'
    $closeButton.Visible = $true
}}

$finishTimer = New-Object System.Windows.Forms.Timer
$finishTimer.Interval = 1400
$finishTimer.Add_Tick({{
    $finishTimer.Stop()
    $form.Close()
}})

$watchTimer = New-Object System.Windows.Forms.Timer
$watchTimer.Interval = 500
$watchTimer.Add_Tick({{
    if (-not $script:started) {{ return }}
    $script:dots = ($script:dots + 1) % 4
    $status.Text = 'Встановлення триває' + ('.' * $script:dots)

    if ($script:installerProcess -and $script:installerProcess.HasExited) {{
        $watchTimer.Stop()
        $progress.Style = 'Blocks'
        $progress.Value = 100
        $status.ForeColor = [System.Drawing.Color]::FromArgb(134, 239, 172)
        $status.Text = 'Оновлення завершено. Запускаємо програму...'
        $finishTimer.Start()
    }}
}})

$startTimer = New-Object System.Windows.Forms.Timer
$startTimer.Interval = 900
$startTimer.Add_Tick({{
    $startTimer.Stop()
    try {{
        if (-not (Test-Path -LiteralPath $InstallerPath)) {{
            throw 'Файл інсталятора не знайдено.'
        }}
        $status.Text = 'Запускаємо інсталятор...'
        $script:installerProcess = Start-Process -FilePath $InstallerPath -ArgumentList $ArgumentLine -PassThru
        $script:started = $true
        $watchTimer.Start()
    }} catch {{
        Set-Failed $_.Exception.Message
    }}
}})

$form.Add_Shown({{ $startTimer.Start() }})
[System.Windows.Forms.Application]::Run($form)
"""
    with open(script_path, "w", encoding="utf-8-sig") as script_file:
        script_file.write(script)
    return script_path


def _launch_visual_updater(installer_path: str, args: list[str], latest_version: str | None):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        raise FileNotFoundError("PowerShell не знайдено")

    script_path = _write_visual_updater_script(
        installer_path,
        subprocess.list2cmdline(args),
        latest_version,
    )
    subprocess.Popen(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _consume_update_notice():
    path = _update_notice_path()
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as notice_file:
            notice = json.load(notice_file)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    target_version = str(notice.get("target_version") or "").strip()
    if target_version and _version_tuple(APP_VERSION) >= _version_tuple(target_version):
        try:
            os.remove(path)
        except OSError:
            pass
        return {
            "just_updated": True,
            "updated_version": APP_VERSION,
        }

    return None


def _used_template_files():
    db = SessionLocal()
    try:
        return {
            row[0]
            for row in db.query(TemplateFile.stored_filename).all()
            if row[0]
        }
    finally:
        db.close()


def _used_auto_message_files():
    db = SessionLocal()
    try:
        return {
            row[0]
            for row in db.query(AutoMessageFile.stored_filename).all()
            if row[0]
        }
    finally:
        db.close()


def _runtime_data_usage():
    root = get_runtime_data_dir()
    total_bytes = 0
    file_count = 0

    if not os.path.isdir(root):
        return {
            "runtime_dir": root,
            "runtime_total_bytes": 0,
            "runtime_total_mb": 0,
            "runtime_file_count": 0,
        }

    for current_root, _dirs, files in os.walk(root):
        for filename in files:
            path = os.path.join(current_root, filename)
            try:
                total_bytes += os.path.getsize(path)
                file_count += 1
            except OSError:
                pass

    return {
        "runtime_dir": root,
        "runtime_total_bytes": total_bytes,
        "runtime_total_mb": round(total_bytes / 1024 / 1024, 2),
        "runtime_file_count": file_count,
    }


def _open_folder(path: str):
    os.makedirs(path, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Не вдалося відкрити папку: {error}")


def _format_bytes(size: int | float | None) -> str:
    value = float(size or 0)
    units = ("B", "KB", "MB", "GB")
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"


def _redact_sensitive(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_GOOGLE_API_KEY]", cleaned)
    cleaned = re.sub(r"(?i)(api[_\s-]*hash\s*[:=]\s*)[0-9a-f]{16,}", r"\1[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(api[_\s-]*key\s*[:=]\s*)\S+", r"\1[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(token\s*[:=]\s*)\S+", r"\1[REDACTED]", cleaned)
    return cleaned


def _read_text_tail(path: str, max_bytes: int = 256 * 1024) -> str:
    if not os.path.exists(path):
        return "File not found."
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as file:
            if size > max_bytes:
                file.seek(size - max_bytes)
                prefix = f"... showing last {_format_bytes(max_bytes)} of {_format_bytes(size)} ...\n"
            else:
                prefix = ""
            data = file.read()
        return _redact_sensitive(prefix + data.decode("utf-8", errors="replace"))
    except Exception as error:
        return f"Could not read file: {error}"


def _append_section(lines: list[str], title: str):
    lines.append("")
    lines.append("=" * 78)
    lines.append(title)
    lines.append("=" * 78)


def _count_table(db, model) -> str:
    try:
        return str(db.query(model).count())
    except Exception as error:
        return f"error: {error}"


def _build_diagnostic_log() -> str:
    now = datetime.now().isoformat(timespec="seconds")
    runtime_dir = get_runtime_data_dir()
    lines: list[str] = []

    lines.append("School Manager diagnostic log")
    lines.append(f"Created at: {now}")
    lines.append("Note: API keys, tokens and known secret-looking values are redacted where possible.")

    _append_section(lines, "Application")
    lines.extend([
        f"App version: {APP_VERSION}",
        f"Python: {sys.version.replace(os.linesep, ' ')}",
        f"Platform: {platform.platform()}",
        f"Executable: {sys.executable}",
        f"Frozen build: {getattr(sys, 'frozen', False)}",
        f"Working directory: {os.getcwd()}",
        f"Runtime data dir: {runtime_dir}",
        f"Database path: {db_path}",
    ])

    _append_section(lines, "Runtime Files")
    for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
        if os.path.exists(path):
            lines.append(f"{os.path.basename(path)}: {_format_bytes(os.path.getsize(path))}")
        else:
            lines.append(f"{os.path.basename(path)}: missing")
    usage = _runtime_data_usage()
    lines.append(f"Runtime files: {usage.get('runtime_file_count', 0)}")
    lines.append(f"Runtime size: {_format_bytes(usage.get('runtime_total_bytes', 0))}")

    _append_section(lines, "Database Summary")
    db = SessionLocal()
    try:
        counts = (
            ("groups", Group),
            ("categories", Category),
            ("templates", Template),
            ("auto_messages", AutoMessage),
            ("parent_report_lessons", ParentReportLesson),
            ("parent_report_runs", ParentReportRun),
            ("app_logs", AppLog),
        )
        for label, model in counts:
            lines.append(f"{label}: {_count_table(db, model)}")

        settings = db.query(BotSettings).first()
        lines.append(f"telegram_settings_exists: {bool(settings)}")
        lines.append(f"telegram_phone_set: {bool(settings and settings.phone)}")
        lines.append(
            "system_notifications_enabled: "
            f"{getattr(settings, 'windows_notifications_enabled', None) if settings else None}"
        )
    except Exception as error:
        lines.append(f"Database summary error: {error}")
    finally:
        db.close()

    _append_section(lines, "Application Event Log (latest 1000)")
    db = SessionLocal()
    try:
        logs = db.query(AppLog).order_by(AppLog.id.desc()).limit(1000).all()
        for log in reversed(logs):
            lines.append(f"[{log.id}] {log.timestamp} {log.level} {log.module}: {_redact_sensitive(log.message)}")
        if not logs:
            lines.append("No application events.")
    except Exception as error:
        lines.append(f"Could not read application event log: {error}")
    finally:
        db.close()

    _append_section(lines, "Parent Reports (latest 200)")
    db = SessionLocal()
    try:
        runs = db.query(ParentReportRun).order_by(ParentReportRun.id.desc()).limit(200).all()
        for run in reversed(runs):
            error = f" error={_redact_sensitive(run.error)}" if run.error else ""
            lines.append(
                f"[{run.id}] {run.created_at} status={run.status} group={run.lesson_group_name} "
                f"date={run.lesson_date} auto={run.is_auto} test={run.is_test}{error}"
            )
        if not runs:
            lines.append("No parent report runs.")
    except Exception as error:
        lines.append(f"Could not read parent report runs: {error}")
    finally:
        db.close()

    _append_section(lines, "Launcher And Backend Logs")
    known_logs = [
        os.path.join(runtime_dir, "launcher.log"),
        os.path.join(runtime_dir, "error_backend.log"),
    ]
    if os.path.isdir(runtime_dir):
        for name in os.listdir(runtime_dir):
            path = os.path.join(runtime_dir, name)
            if name.lower().endswith(".log") and path not in known_logs:
                known_logs.append(path)

    for path in known_logs:
        lines.append("")
        lines.append(f"--- {os.path.basename(path)} ---")
        lines.append(_read_text_tail(path))

    _append_section(lines, "End")
    lines.append("Diagnostic log completed.")
    return "\n".join(lines) + "\n"


def _version_tuple(v: str):
    """Конвертує рядок версії '1.2' у tuple (1, 2) для порівняння."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


async def _fetch_update_info():
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        response = await client.get(
            UPDATE_CHECK_URL,
            params={"_": str(int(datetime.now().timestamp()))},
            headers={"Cache-Control": "no-cache"},
        )
        response.raise_for_status()
        return response.json()


def _current_update_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform or "unknown"


def _download_entry_url(entry) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("url") or entry.get("download_url") or "").strip()
    return ""


def _select_platform_download(data: dict) -> dict:
    platform_key = _current_update_platform()
    downloads = data.get("downloads") if isinstance(data, dict) else None
    entry = None

    if isinstance(downloads, dict):
        aliases = {
            "windows": ("windows", "win", "win32", "win64"),
            "macos": ("macos", "mac", "darwin", "osx"),
        }.get(platform_key, (platform_key,))
        for alias in aliases:
            if alias in downloads:
                entry = downloads.get(alias)
                break

    url = _download_entry_url(entry)
    if not url and platform_key == "windows":
        url = str(data.get("download_url") or "").strip()

    can_auto_install = platform_key == "windows"
    filename = _update_package_filename(platform_key, url)
    return {
        "platform": platform_key,
        "url": url,
        "file_name": filename,
        "can_auto_install": can_auto_install,
        "requires_manual_install": platform_key == "macos",
    }


def _update_package_filename(platform_key: str, url: str = "") -> str:
    fallback = UPDATE_PACKAGE_FILENAMES.get(platform_key, "SchoolManager_Update.bin")
    try:
        name = os.path.basename(urlparse(url).path)
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
        if name:
            return name
    except Exception:
        pass
    return fallback


def _autostart_supported() -> bool:
    return autostart_status(START_IN_TRAY_ARG)["supported"]


def _autostart_command() -> str:
    return autostart_status(START_IN_TRAY_ARG)["expected_command"]


def _read_autostart_value() -> str | None:
    return read_autostart_value()


def _write_autostart_value(enabled: bool):
    write_autostart_value(enabled, START_IN_TRAY_ARG)


def _autostart_status():
    return autostart_status(START_IN_TRAY_ARG)


def _notifications_supported() -> bool:
    return system_notifications_supported()


def _notifications_status():
    db = SessionLocal()
    try:
        settings = db.query(BotSettings).first()
        enabled = True if not settings else bool(getattr(settings, "windows_notifications_enabled", 1))
        return {
            "supported": _notifications_supported(),
            "enabled": enabled,
        }
    finally:
        db.close()


def _write_notifications_enabled(enabled: bool):
    db = SessionLocal()
    try:
        settings = db.query(BotSettings).first()
        if not settings:
            settings = BotSettings()
            db.add(settings)
            db.flush()
        settings.windows_notifications_enabled = 1 if enabled else 0
        db.commit()
        return {
            "supported": _notifications_supported(),
            "enabled": bool(settings.windows_notifications_enabled),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/version")
async def get_version():
    """
    Повертає поточну версію та, якщо налаштовано URL,
    перевіряє наявність оновлення.
    """
    result = {
        "current_version": APP_VERSION,
        "update_available": False,
        "latest_version": None,
        "download_url": None,
        "download_platform": _current_update_platform(),
        "download_file_name": None,
        "can_auto_install": _current_update_platform() == "windows",
        "requires_manual_install": _current_update_platform() == "macos",
        "platform_supported": False,
        "changelog": None,
        "check_enabled": bool(UPDATE_CHECK_URL),
        "just_updated": False,
        "updated_version": None,
    }

    update_notice = _consume_update_notice()
    if update_notice:
        result.update(update_notice)

    if not UPDATE_CHECK_URL:
        return result

    try:
        data = await _fetch_update_info()

        latest = str(data.get("latest_version", "")).strip()
        selected_download = _select_platform_download(data)
        result["latest_version"] = latest or None
        result["download_url"] = selected_download["url"]
        result["download_platform"] = selected_download["platform"]
        result["download_file_name"] = selected_download["file_name"]
        result["can_auto_install"] = selected_download["can_auto_install"]
        result["requires_manual_install"] = selected_download["requires_manual_install"]
        result["platform_supported"] = bool(selected_download["url"])
        result["changelog"] = data.get("changelog", "")

        if latest and selected_download["url"] and _version_tuple(latest) > _version_tuple(APP_VERSION):
            result["update_available"] = True
    except Exception as e:
        # Не кидаємо помилку — просто повертаємо без даних про оновлення
        result["check_error"] = str(e)

    return result


@router.get("/cache/status")
def get_cache_status():
    status = cache_status(_used_template_files(), _used_auto_message_files())
    status.update(sticker_cache_status())
    status.update(_runtime_data_usage())
    return status


@router.post("/cache/open-folder")
def open_cache_folder():
    path = get_runtime_data_dir()
    _open_folder(path)
    return {"ok": True, "path": path}


@router.post("/cache/cleanup")
def cleanup_app_cache():
    result = cleanup_cache(
        _used_template_files(),
        _used_auto_message_files(),
        clear_import_cache=True,
    )
    result["freed_mb"] = round(result["freed_bytes"] / 1024 / 1024, 2)
    log_event(
        "INFO",
        "System",
        f"Очищення кешу: видалено {result['deleted_count']} файлів, звільнено {result['freed_mb']} MB"
    )
    return {"ok": True, **result}


@router.post("/cache/stickers/cleanup")
def cleanup_stickers_cache():
    result = clear_sticker_cache()
    log_event(
        "INFO",
        "System",
        f"Очищення кешу наліпок: видалено {result['deleted_count']} файлів, звільнено {result['freed_mb']} MB"
    )
    return {"ok": True, **result}


@router.get("/diagnostics/log-file")
def download_diagnostic_log():
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"school_manager_log_{date_str}.txt"
    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        content = _build_diagnostic_log()
        with open(tmp_path, "w", encoding="utf-8-sig", newline="\n") as output:
            output.write(content)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Не вдалося сформувати log файл: {error}")

    log_event("INFO", "System", "Діагностичний log файл сформовано")
    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="text/plain; charset=utf-8",
    )


@router.get("/autostart")
def get_autostart():
    return _autostart_status()


@router.post("/autostart")
def set_autostart(payload: AutostartRequest):
    _write_autostart_value(payload.enabled)
    status = _autostart_status()
    log_event(
        "INFO",
        "System",
        "Автозапуск програми увімкнено" if payload.enabled else "Автозапуск програми вимкнено"
    )
    return {"ok": True, **status}


@router.get("/notifications")
def get_windows_notifications():
    return _notifications_status()


@router.post("/notifications")
def set_windows_notifications(payload: NotificationsRequest):
    status = _write_notifications_enabled(payload.enabled)
    log_event(
        "INFO",
        "System",
        "Системні сповіщення увімкнено" if payload.enabled else "Системні сповіщення вимкнено"
    )
    return {"ok": True, **status}


@router.get("/update/progress")
def get_update_progress():
    """Повертає поточний стан завантаження оновлення."""
    return _get_update_state()


@router.post("/update/download")
async def start_update_download(background_tasks: BackgroundTasks, payload: Optional[UpdateDownloadRequest] = None):
    """
    Починає фонове завантаження нового встановлювача.
    Спочатку перевіряє URL оновлення.
    """
    state = _get_update_state()
    if state["status"] in {"checking", "downloading", "installing"}:
        return {"ok": False, "error": "Завантаження вже йде"}

    payload = payload or UpdateDownloadRequest()
    _set_update_state(
        status="checking",
        progress=0,
        error=None,
        download_url=None,
        file_path=None,
        latest_version=None,
        downloaded_bytes=0,
        total_bytes=0,
        auto_install=payload.auto_install,
        platform=_current_update_platform(),
        file_name=None,
        can_auto_install=_current_update_platform() == "windows",
        requires_manual_install=_current_update_platform() == "macos",
    )

    # Отримуємо посилання на файл
    if not UPDATE_CHECK_URL:
        return {"ok": False, "error": "URL перевірки оновлень не налаштовано"}

    try:
        data = await _fetch_update_info()
        selected_download = _select_platform_download(data)
        download_url = selected_download["url"]
        latest_version = str(data.get("latest_version", "")).strip()
        if not download_url:
            _set_update_state(status="error", error="Посилання на завантаження відсутнє")
            return {"ok": False, "error": "Посилання на завантаження відсутнє"}
        if _version_tuple(latest_version) <= _version_tuple(APP_VERSION):
            _set_update_state(status="idle", progress=0, error=None)
            return {"ok": False, "error": "Нова версія не знайдена"}
    except Exception as e:
        _set_update_state(status="error", error=f"Не вдалося отримати дані оновлення: {e}")
        return {"ok": False, "error": f"Не вдалося отримати дані оновлення: {e}"}

    # Скидаємо стан і запускаємо фонове завантаження
    _set_update_state(
        status="downloading",
        progress=0,
        error=None,
        download_url=download_url,
        file_path=None,
        latest_version=latest_version,
        downloaded_bytes=0,
        total_bytes=0,
        auto_install=payload.auto_install,
        platform=selected_download["platform"],
        file_name=selected_download["file_name"],
        can_auto_install=selected_download["can_auto_install"],
        requires_manual_install=selected_download["requires_manual_install"],
    )

    background_tasks.add_task(_download_update, download_url, latest_version, payload.auto_install, selected_download)
    return {"ok": True, "message": "Завантаження розпочато"}


def _get_remote_file_size(client: httpx.Client, url: str) -> int:
    try:
        response = client.head(url)
        response.raise_for_status()
        return int(response.headers.get("content-length") or 0)
    except Exception:
        return 0


def _launch_update_installer(file_path: str, latest_version: str | None = None, silent: bool = True) -> bool:
    if not os.path.exists(file_path):
        raise FileNotFoundError("Файл оновлення не знайдено")

    if sys.platform == "darwin":
        _set_update_state(status="installing", progress=100, file_path=file_path, error=None)
        subprocess.Popen(["open", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        log_event("INFO", "Update", f"macOS update image opened: {file_path}")
        return False

    if sys.platform != "win32":
        _set_update_state(status="installing", progress=100, file_path=file_path, error=None)
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        else:
            subprocess.Popen([file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        return False

    _write_update_notice(latest_version)
    args = [file_path, *INNO_SILENT_ARGS] if silent else [file_path]
    _set_update_state(status="installing", progress=100, file_path=file_path, error=None)

    if sys.platform == "win32" and silent:
        try:
            _launch_visual_updater(file_path, INNO_SILENT_ARGS, latest_version)
            return True
        except Exception as error:
            log_event("WARNING", "Update", f"Вікно оновлення не запустилося, запускаємо інсталятор напряму: {error}")

    command_line = "timeout /t 2 /nobreak >NUL & " + subprocess.list2cmdline(args)
    subprocess.Popen(
        ["cmd.exe", "/c", command_line],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    return True


def _download_update(
    url: str,
    latest_version: str | None = None,
    auto_install: bool = True,
    selected_download: dict | None = None,
):
    """
    Фонова функція завантаження файлу з прогрес-баром.
    Зберігає файл у тимчасову теку, потім запускає і закриває сервер.
    """
    try:
        # Визначаємо директорію для завантаження (поруч із .exe або в теці бекенду)
        save_dir = get_runtime_data_dir()
        os.makedirs(save_dir, exist_ok=True)

        selected_download = selected_download or _select_platform_download({"download_url": url})
        package_filename = selected_download.get("file_name") or _update_package_filename(selected_download.get("platform") or _current_update_platform(), url)
        save_path = os.path.join(save_dir, package_filename)
        temp_path = f"{save_path}.part"

        # Завантажуємо з відображенням прогресу
        timeout = httpx.Timeout(300.0, connect=30.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            expected_total = _get_remote_file_size(client, url)
            if expected_total > 0:
                _set_update_state(total_bytes=expected_total)

            with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or expected_total or 0)
                downloaded = 0
                _set_update_state(total_bytes=total, downloaded_bytes=0, progress=0)

                with open(temp_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress = _get_update_state().get("progress") or 0
                            if total > 0:
                                progress = max(1, min(99, int(downloaded / total * 100)))
                            _set_update_state(downloaded_bytes=downloaded, total_bytes=total, progress=progress)

        os.replace(temp_path, save_path)
        _set_update_state(progress=100, downloaded_bytes=os.path.getsize(save_path), file_path=save_path, status="done")
        log_event("INFO", "Update", f"Оновлення {latest_version or ''} завантажено: {save_path}")

        if auto_install:
            should_exit = _launch_update_installer(save_path, latest_version=latest_version, silent=True)
            if should_exit:
                os._exit(0)

    except Exception as e:
        try:
            selected_download = selected_download or _select_platform_download({"download_url": url})
            package_filename = selected_download.get("file_name") or _update_package_filename(selected_download.get("platform") or _current_update_platform(), url)
            temp_path = os.path.join(get_runtime_data_dir(), f"{package_filename}.part")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            for name in UPDATE_PACKAGE_FILENAMES.values():
                temp_path = os.path.join(get_runtime_data_dir(), f"{name}.part")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        except Exception:
            pass
        _set_update_state(status="error", error=str(e))
        log_event("ERROR", "Update", f"Помилка оновлення: {e}")


@router.post("/update/launch")
def launch_update():
    """
    Запускає завантажений встановлювач і зупиняє сервер.
    Виконується тільки після статусу 'done'.
    """
    state = _get_update_state()
    if state["status"] != "done":
        return {"ok": False, "error": "Файл ще не завантажено"}

    file_path = state.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return {"ok": False, "error": "Файл оновлення не знайдено"}

    # Запускаємо встановлювач у фоні та через 1 сек вбиваємо поточний процес
    def _launch_and_exit():
        should_exit = _launch_update_installer(file_path, latest_version=state.get("latest_version"), silent=True)
        if should_exit:
            os._exit(0)  # Завершуємо сервер

    threading.Thread(target=_launch_and_exit, daemon=True).start()
    if _current_update_platform() == "macos":
        return {"ok": True, "message": "Update image opened. Drag SchoolManager.app to Applications."}
    return {"ok": True, "message": "Встановлювач запущено. Програма закривається..."}


# ==========================================
# РЕЗЕРВНЕ КОПІЮВАННЯ / ВІДНОВЛЕННЯ
# ==========================================

@router.get("/backup")
def download_backup():
    """
    Завантажує резервну копію бази даних (school_manager.db).
    """
    if not os.path.exists(db_path):
        return JSONResponse(status_code=404, content={"error": "Базу даних не знайдено"})

    # Створюємо бекап з датою у назві файлу
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    backup_filename = f"school_manager_backup_{date_str}.db"

    # Копіюємо файл у тимчасову папку (щоб не заблокувати оригінал)
    tmp_dir = tempfile.gettempdir()
    tmp_path = os.path.join(tmp_dir, backup_filename)
    shutil.copy2(db_path, tmp_path)

    return FileResponse(
        path=tmp_path,
        filename=backup_filename,
        media_type="application/octet-stream"
    )


@router.post("/restore")
async def restore_backup(file: UploadFile = File(...)):
    """
    Відновлює базу даних з завантаженого файлу .db.
    Створює автоматичний бекап перед заміною.
    """
    if not file.filename.endswith(".db"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Файл повинен мати розширення .db"}
        )

    # Створюємо автобекап поточної БД перед заміною
    if os.path.exists(db_path):
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        auto_backup_path = db_path.replace(".db", f"_before_restore_{date_str}.db")
        shutil.copy2(db_path, auto_backup_path)

    # Записуємо новий файл
    content = await file.read()
    with open(db_path, "wb") as f:
        f.write(content)

    return {"ok": True, "message": "Базу даних успішно відновлено. Перезапустіть додаток для застосування змін."}
