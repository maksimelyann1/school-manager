from datetime import datetime
import sys

from database import SessionLocal
from models import AppLog


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")


def log_event(level: str, module: str, message: str):
    """
    Save an application event to the database and mirror it to stdout when possible.
    Console output is sanitized because some Windows consoles cannot encode Telegram
    display names with decorative Unicode characters.
    """
    timestamp = datetime.now().isoformat()

    try:
        print(_console_safe(f"[{module}] [{level}] {message}"))
    except Exception:
        pass

    db = SessionLocal()
    try:
        new_log = AppLog(
            timestamp=timestamp,
            level=level.upper(),
            module=module,
            message=message,
        )
        db.add(new_log)
        db.commit()
    except Exception as error:
        try:
            print(_console_safe(f"[Logger] Failed to write log entry: {error}"))
        except Exception:
            pass
    finally:
        db.close()
