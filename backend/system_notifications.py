import json
import os
import subprocess
import sys

from database import SessionLocal
from logger import log_event
from models import BotSettings


APP_NOTIFICATION_NAME = "School Manager"


def system_notifications_supported() -> bool:
    return sys.platform in {"win32", "darwin"}


def _settings_enabled() -> bool:
    db = SessionLocal()
    try:
        settings = db.query(BotSettings).first()
        if not settings:
            return True
        return bool(getattr(settings, "windows_notifications_enabled", 1))
    except Exception as error:
        log_event("WARNING", "System", f"Не вдалося прочитати налаштування системних сповіщень: {error}")
        return True
    finally:
        db.close()


def _notification_icon_path() -> str:
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = []

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = getattr(sys, "_MEIPASS", "")
        candidates.extend([
            os.path.join(exe_dir, "app.ico"),
            os.path.join(exe_dir, "logo.png"),
            os.path.join(meipass, "app.ico"),
            os.path.join(meipass, "logo.png"),
        ])

    candidates.extend([
        os.path.join(app_root, "app.ico"),
        os.path.join(app_root, "logo.png"),
        os.path.join(app_root, "frontend", "src", "assets", "logo.png"),
    ])

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def _show_windows_notification(title: str, message: str) -> bool:
    try:
        from winotify import Notification
    except Exception as error:
        log_event("WARNING", "System", f"winotify недоступний, системне сповіщення пропущено: {error}")
        return False

    try:
        toast = Notification(
            app_id=APP_NOTIFICATION_NAME,
            title=title,
            msg=message,
            icon=_notification_icon_path(),
            duration="short",
        )
        toast.show()
        return True
    except Exception as error:
        log_event("WARNING", "System", f"Не вдалося показати системне сповіщення Windows: {error}")
        return False


def _show_macos_notification(title: str, message: str) -> bool:
    try:
        script = (
            f"display notification {json.dumps(str(message))} "
            f"with title {json.dumps(str(title or APP_NOTIFICATION_NAME))}"
        )
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except Exception as error:
        log_event("WARNING", "System", f"Не вдалося показати системне сповіщення macOS: {error}")
        return False


def show_system_notification(title: str, message: str) -> bool:
    if not system_notifications_supported() or not _settings_enabled():
        return False

    if sys.platform == "win32":
        return _show_windows_notification(title, message)
    if sys.platform == "darwin":
        return _show_macos_notification(title, message)
    return False
