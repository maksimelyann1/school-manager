"""Telegram report delivery with a durable caller-supplied deduplication ID."""
from datetime import datetime, timedelta

from pyrogram import raw, utils
from pyrogram.errors import FloodWait, RPCError

from telegram_send_queue import telegram_send_queue


UNCERTAIN_MESSAGE = (
    "Telegram не підтвердив доставку. Повідомлення могло бути надіслане; "
    "повторну відправку заблоковано до перевірки історії Telegram."
)


def is_ambiguous_error(error: str | None) -> bool:
    value = (error or "").lower()
    return any(part in value for part in (
        "timed out", "timeout", "connection lost", "connection reset", "connection aborted",
        "не підтвердив доставку",
    ))


async def send_report_message(client, chat_id: str, text: str, random_id: str, label: str) -> dict:
    # Build once: queue retries must reuse both the exact text and random_id.
    try:
        parsed = await utils.parse_text_entities(client, text, None, None)
        request = raw.functions.messages.SendMessage(
            peer=await client.resolve_peer(int(chat_id)),
            random_id=int(random_id),
            message=parsed["message"],
            entities=parsed["entities"],
        )
    except Exception as error:
        return {"ok": False, "uncertain": False, "description": str(error)}

    uncertain_attempt = False

    async def action():
        nonlocal uncertain_attempt
        try:
            response = await client.invoke(request, retries=0, timeout=25, sleep_threshold=0)
            message_id = getattr(response, "id", None)
            for update in getattr(response, "updates", []):
                if isinstance(update, raw.types.UpdateMessageID) and update.random_id == int(random_id):
                    message_id = update.id
                    break
                if isinstance(update, (raw.types.UpdateNewMessage, raw.types.UpdateNewChannelMessage)):
                    message_id = update.message.id
            if message_id is None:
                return {"ok": False, "uncertain": True, "retryable": False,
                        "description": UNCERTAIN_MESSAGE}
            return {"ok": True, "message_id": message_id}
        except FloodWait as error:
            return {"ok": False, "uncertain": uncertain_attempt, "retryable": False,
                    "description": f"Telegram просить зачекати {error.value} с"}
        except RPCError as error:
            # A server rejection is definite only for 4xx; 5xx may follow acceptance.
            return {"ok": False, "uncertain": uncertain_attempt or getattr(error, "CODE", 500) >= 500
                    or "RANDOM_ID_DUPLICATE" in str(error),
                    "retryable": False, "description": str(error)}
        except Exception as error:
            uncertain_attempt = True
            return {"ok": False, "uncertain": True, "description": str(error)}

    return await telegram_send_queue.run(label, action, retries=2)


async def find_delivered_report(client, chat_id: str, text: str, created_at: str,
                                *, legacy: bool = False) -> int | None:
    """Match only own messages, exact rendered content and a bounded send window."""
    parsed = await utils.parse_text_entities(client, text, None, None)
    expected = parsed["message"].strip()
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None:
        created = created.astimezone()
    earliest = created - timedelta(minutes=20 if legacy else 1)
    latest = created + timedelta(minutes=30)
    async for message in client.get_chat_history(int(chat_id), limit=200):
        sent_at = message.date
        if not sent_at:
            continue
        if sent_at.tzinfo is None:
            sent_at = sent_at.astimezone()
        if sent_at < earliest:
            break
        if sent_at > latest:
            continue
        if message.outgoing and str(message.text or message.caption or "").strip() == expected:
            return message.id
    return None
