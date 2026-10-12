"""Internal, read-only destinations for desktop notification activation."""
from datetime import date
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID

PROTOCOL = "schoolmanager"
DEV_PROTOCOL = "schoolmanager-dev"
_PARAMETERS = {
    "/": {},
    "/parents-report": {"tab": {"pending", "runs"}, "lesson_id": "number", "run_id": "number"},
    "/tasks": {"item_id": "uuid", "date": "date", "bucket": {"calendar", "overdue", "reminders"}},
    "/auto-messages": {"message_id": "number"},
}


def normalize_target(target: str) -> str:
    if not isinstance(target, str) or len(target) > 2048 or any(ord(c) < 32 for c in target):
        raise ValueError("Некоректна адреса сповіщення")
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.fragment or parts.path not in _PARAMETERS:
        raise ValueError("Невідомий розділ сповіщення")
    values = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    if len({key for key, _ in values}) != len(values):
        raise ValueError("Повторені параметри сповіщення")
    for key, value in values:
        rule = _PARAMETERS[parts.path].get(key)
        if rule is None or not value or len(value) > 100:
            raise ValueError("Невідомий параметр сповіщення")
        if isinstance(rule, set):
            valid = value in rule
        elif rule == "number":
            valid = bool(re.fullmatch(r"[1-9][0-9]{0,18}", value))
        elif rule == "uuid":
            UUID(value)
            valid = True
        else:
            valid = date.fromisoformat(value).isoformat() == value
        if not valid:
            raise ValueError("Некоректний параметр сповіщення")
    return parts.path + ("?" + urlencode(values) if values else "")


def notification_uri(target: str = "/") -> str:
    protocol = PROTOCOL if getattr(sys, "frozen", False) else DEV_PROTOCOL
    return f"{protocol}://open{normalize_target(target)}"


def target_from_uri(uri: str) -> str:
    if not isinstance(uri, str) or len(uri) > 2200 or any(ord(c) < 32 for c in uri):
        raise ValueError("Некоректне посилання сповіщення")
    parts = urlsplit(uri)
    if parts.scheme not in {PROTOCOL, DEV_PROTOCOL} or parts.netloc != "open" or parts.fragment:
        raise ValueError("Невідоме посилання сповіщення")
    return normalize_target((parts.path or "/") + ("?" + parts.query if parts.query else ""))
