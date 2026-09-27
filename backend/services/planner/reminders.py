import asyncio
from datetime import datetime, timedelta, timezone
import secrets
from sqlalchemy import and_, or_

from pyrogram import raw
from pyrogram.errors import FloodWait, RPCError

from database import SessionLocal
from logger import log_event
from pyrogram_client import pyrogram_manager
from system_notifications import show_system_notification
from task_models import PlannerItem, PlannerReminder
from telegram_send_queue import telegram_send_queue
from services.planner.items import utc_now, serialize

reminder_lock = asyncio.Lock()


def reminder_text(item, reminder):
    value = serialize(item)
    details = ' '.join(part for part in (value['date'], value['time']) if part)
    return f'🔔 {item.title}\n{details}\n\nНагадування №{reminder.id[:12]}'


async def scheduled_history(client, peer):
    response = await client.invoke(raw.functions.messages.GetScheduledHistory(peer=peer, hash=0), retries=0, timeout=20, sleep_threshold=0)
    return getattr(response, 'messages', [])


async def process_telegram(db, item, reminder, now):
    if not pyrogram_manager.is_connected or not pyrogram_manager.client:
        return
    client = pyrogram_manager.client
    me = await client.get_me()
    if reminder.account_id and reminder.account_id != str(me.id):
        reminder.error = 'Нагадування належить іншому Telegram-акаунту. Підключіть його для зміни'
        db.commit()
        return
    reminder.account_id = str(me.id)
    peer = await client.resolve_peer(me.id)
    target = datetime.fromisoformat(reminder.remind_at)
    if reminder.state in {'uncertain', 'cancel_pending'} or reminder.scheduled_message_id:
        history = await scheduled_history(client, peer)
        match = next((m for m in history if (reminder.scheduled_message_id and m.id == reminder.scheduled_message_id) or f'Нагадування №{reminder.id[:12]}' in (getattr(m, 'message', '') or '')), None)
        if match:
            reminder.scheduled_message_id = match.id
        elif reminder.state == 'cancel_pending':
            reminder.state = 'cancelled'
            reminder.updated_at = utc_now()
            db.commit()
            return
        elif target <= now:
            reminder.state, reminder.updated_at = 'elapsed', utc_now()
            db.commit()
            return
        elif reminder.state == 'uncertain' or reminder.scheduled_message_id:
            reminder.state = 'uncertain'
            reminder.error = 'Telegram не підтвердив стан. Перевірте відкладені повідомлення у «Збереженому»'
            reminder.next_attempt_at = (now + timedelta(minutes=5)).isoformat()
            db.commit()
            return
        if reminder.state == 'scheduled':
            return
    if target <= now and reminder.state != 'cancel_pending':
        reminder.state, reminder.updated_at = 'missed', utc_now()
        db.commit()
        return
    revision, desired_state = reminder.revision, reminder.state
    reminder.random_id = reminder.random_id or str(secrets.randbits(63) or 1)
    if desired_state == 'cancel_pending':
        request = raw.functions.messages.DeleteScheduledMessages(peer=peer, id=[reminder.scheduled_message_id])
    elif reminder.scheduled_message_id:
        request = raw.functions.messages.EditMessage(peer=peer, id=reminder.scheduled_message_id,
            message=reminder_text(item, reminder), schedule_date=int(target.timestamp()))
    else:
        request = raw.functions.messages.SendMessage(peer=peer, random_id=int(reminder.random_id),
            message=reminder_text(item, reminder), schedule_date=int(target.timestamp()))
    if desired_state != 'cancel_pending':
        reminder.state = 'uncertain'
    reminder.updated_at = utc_now()
    db.commit()

    async def send():
        db.refresh(reminder)
        db.refresh(item)
        if desired_state != 'cancel_pending' and (reminder.revision != revision or reminder.state == 'cancel_pending' or item.deleted_at or item.status != 'open'):
            return {'ok': False, 'stale': True}
        if desired_state != 'cancel_pending' and target <= datetime.now(timezone.utc):
            return {'ok': False, 'expired': True}
        try:
            result = await client.invoke(request, retries=0, timeout=25, sleep_threshold=0)
            message_id = reminder.scheduled_message_id
            for event in getattr(result, 'updates', []):
                if isinstance(event, raw.types.UpdateNewScheduledMessage):
                    message_id = event.message.id
            return {'ok': True, 'message_id': message_id}
        except FloodWait as err:
            return {'ok': False, 'definite': True, 'delay': max(60, err.value), 'description': 'Telegram обмежив частоту. Повторимо пізніше'}
        except RPCError as err:
            return {'ok': False, 'definite': getattr(err, 'CODE', 500) < 500 and 'RANDOM_ID_DUPLICATE' not in str(err), 'description': f'Telegram відхилив нагадування ({type(err).__name__})'}
        except Exception:
            return {'ok': False, 'definite': False, 'description': 'Telegram не підтвердив планування. Перевіряємо відкладені повідомлення'}

    result = await telegram_send_queue.run(f'Нагадування {reminder.id[:12]}', send, retries=0, module='Planner')
    db.refresh(reminder)
    if result.get('stale'):
        if reminder.state != 'cancel_pending':
            reminder.state = 'pending'
        db.commit()
        return
    if result.get('expired'):
        reminder.state, reminder.updated_at = 'missed', utc_now()
        db.commit()
        return
    if result['ok']:
        reminder.scheduled_message_id = result.get('message_id')
        if desired_state == 'cancel_pending':
            reminder.state = 'cancelled'
        elif reminder.state != 'cancel_pending' and reminder.revision == revision:
            reminder.state = 'scheduled' if reminder.scheduled_message_id else 'uncertain'
        reminder.error = None
    else:
        reminder.attempts += 1
        reminder.error = result['description']
        if reminder.state != 'cancel_pending' and result.get('definite'):
            reminder.state = 'error' if reminder.attempts >= 5 else 'pending'
        reminder.next_attempt_at = (now + timedelta(seconds=result.get('delay', min(3600, 60 * 2 ** min(reminder.attempts, 5))))).isoformat()
    reminder.updated_at = utc_now()
    db.commit()


async def process_reminders():
    if reminder_lock.locked():
        return
    async with reminder_lock:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            rows = db.query(PlannerReminder).filter(PlannerReminder.state.in_(['pending', 'scheduled', 'uncertain', 'cancel_pending']), or_(
                and_(PlannerReminder.channel == 'telegram', PlannerReminder.state != 'scheduled'),
                PlannerReminder.remind_at <= now.isoformat())).order_by(PlannerReminder.remind_at).limit(200).all()
            missed = 0
            for reminder in rows:
                if reminder.next_attempt_at and reminder.next_attempt_at > now.isoformat():
                    continue
                item = db.get(PlannerItem, reminder.item_id)
                if not item:
                    continue
                try:
                    if reminder.channel == 'telegram':
                        # Future confirmed messages need no polling until edited or due.
                        if reminder.state != 'scheduled' or reminder.remind_at <= now.isoformat():
                            await process_telegram(db, item, reminder, now)
                    elif reminder.remind_at <= now.isoformat():
                        if item.deleted_at or item.status != 'open':
                            reminder.state = 'cancelled'
                        elif now - datetime.fromisoformat(reminder.remind_at) > timedelta(minutes=5):
                            reminder.state = 'missed'
                            missed += 1
                        else:
                            reminder.state = 'sent'
                            reminder.updated_at = utc_now()
                            db.commit()  # At-most-once local notification after process restart.
                            shown = await asyncio.to_thread(show_system_notification, 'Нагадування · School Manager', item.title)
                            if not shown:
                                reminder.state, reminder.error = 'missed', 'Системні сповіщення вимкнені або недоступні'
                        reminder.updated_at = utc_now()
                        db.commit()
                except Exception as error:
                    db.rollback()
                    reminder = db.get(PlannerReminder, reminder.id)
                    message = f'Не вдалося обробити нагадування ({type(error).__name__})'
                    if reminder.error != message:
                        log_event('ERROR', 'Planner', f'{message}, ID {reminder.id}')
                    reminder.error = message
                    reminder.next_attempt_at = (now + timedelta(minutes=5)).isoformat()
                    db.commit()
            if missed:
                await asyncio.to_thread(show_system_notification, 'Пропущені нагадування', f'Поки застосунок був неактивний, минув час {missed} нагадувань. Перегляньте задачник.')
            cutoff = (now - timedelta(days=30)).isoformat()
            db.query(PlannerReminder).filter(PlannerReminder.state.in_(['sent', 'cancelled', 'elapsed', 'missed']), PlannerReminder.updated_at < cutoff).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


def init_scheduler(scheduler):
    from services.planner.google_sync import sync_google
    scheduler.add_job(process_reminders, 'interval', seconds=60, id='planner_reminders', replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(sync_google, 'interval', seconds=60, id='planner_google', replace_existing=True, max_instances=1, coalesce=True)
