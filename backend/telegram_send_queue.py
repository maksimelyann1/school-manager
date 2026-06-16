import asyncio
import re
import time
from typing import Awaitable, Callable

from logger import log_event


DEFAULT_SEND_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 60


NON_RETRYABLE_MARKERS = (
    "CHAT_WRITE_FORBIDDEN",
    "USER_BANNED_IN_CHANNEL",
    "PEER_ID_INVALID",
    "CHAT_ADMIN_REQUIRED",
    "MEDIA_CAPTION_TOO_LONG",
    "MESSAGE_TOO_LONG",
    "немає права писати",
    "некоректний або недоступний Telegram ID",
    "потрібні права адміністратора",
    "підпис до файлу занадто довгий",
    "текст повідомлення занадто довгий",
    "Pyrogram не підключено",
    "Немає тексту, файлів або наліпок",
)


def _human_reason(result_or_error) -> str:
    if isinstance(result_or_error, dict):
        return str(
            result_or_error.get("description")
            or result_or_error.get("error")
            or "Telegram не прийняв відправку"
        )
    return str(result_or_error) or result_or_error.__class__.__name__


def _extract_retry_after_seconds(reason: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:с|сек|seconds?)", reason or "", flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return max(1, min(int(match.group(1)), MAX_RETRY_DELAY_SECONDS))
    except ValueError:
        return None


def _retry_delay(attempt: int, result: dict | None, reason: str) -> float:
    retry_after = None
    if isinstance(result, dict):
        raw_retry_after = result.get("retry_after")
        try:
            retry_after = int(raw_retry_after) if raw_retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None

    retry_after = retry_after or _extract_retry_after_seconds(reason)
    if retry_after:
        return min(retry_after, MAX_RETRY_DELAY_SECONDS)

    return min(1.5 * (attempt + 1), 5.0)


def _is_retryable(result: dict | None, reason: str) -> bool:
    if isinstance(result, dict) and result.get("retryable") is False:
        return False

    normalized = reason or ""
    if any(marker in normalized for marker in NON_RETRYABLE_MARKERS):
        return False

    return True


class TelegramSendQueue:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._ticket = 0

    async def run(
        self,
        label: str,
        action: Callable[[], Awaitable[dict]],
        *,
        retries: int = DEFAULT_SEND_RETRIES,
        module: str = "TelegramQueue",
    ) -> dict:
        self._ticket += 1
        ticket = self._ticket
        label = label or f"Telegram send #{ticket}"
        queued_at = time.monotonic()

        if self._lock.locked():
            log_event("INFO", module, f"Додано в чергу Telegram: {label}")

        async with self._lock:
            wait_seconds = round(time.monotonic() - queued_at, 2)
            if wait_seconds >= 0.2:
                log_event("INFO", module, f"Старт з черги Telegram: {label}; очікування {wait_seconds} с")

            last_result: dict | None = None
            for attempt in range(retries + 1):
                attempt_number = attempt + 1
                try:
                    result = await action()
                except Exception as error:
                    result = {
                        "ok": False,
                        "description": _human_reason(error),
                        "exception": error.__class__.__name__,
                    }

                if result.get("ok"):
                    result.setdefault("attempts", attempt_number)
                    result.setdefault("queue_wait_seconds", wait_seconds)
                    if attempt > 0:
                        log_event("INFO", module, f"Telegram відправив після повтору {attempt_number}: {label}")
                    return result

                last_result = result
                reason = _human_reason(result)
                can_retry = attempt < retries and _is_retryable(result, reason)

                if not can_retry:
                    log_event(
                        "WARNING",
                        module,
                        f"Telegram не прийняв: {label}. Причина: {reason}. Повторів: {attempt}",
                    )
                    result.setdefault("attempts", attempt_number)
                    result.setdefault("queue_wait_seconds", wait_seconds)
                    return result

                delay = _retry_delay(attempt, result, reason)
                log_event(
                    "WARNING",
                    module,
                    f"Telegram не прийняв: {label}. Причина: {reason}. Повтор {attempt_number}/{retries + 1} через {delay:g} с",
                )
                await asyncio.sleep(delay)

            final_result = last_result or {
                "ok": False,
                "description": "Telegram не прийняв відправку після повторних спроб",
            }
            final_reason = _human_reason(final_result)
            log_event(
                "ERROR",
                module,
                f"Telegram не прийняв після {retries + 1} спроб: {label}. Причина: {final_reason}",
            )
            final_result.setdefault("attempts", retries + 1)
            final_result.setdefault("queue_wait_seconds", wait_seconds)
            final_result["retry_exhausted"] = True
            return final_result


telegram_send_queue = TelegramSendQueue()
