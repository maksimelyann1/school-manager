# API для налаштувань та авторизації Pyrogram
import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import BotSettings
from schemas import BotSettingsCreate, BotSettingsResponse, QRLoginRequest, SendCodeRequest, VerifyCodeRequest, Verify2FARequest
from pyrogram_client import pyrogram_manager
from logger import log_event
from routers.groups import sync_telegram_groups
from routers.stickers import cancel_sticker_cache_warmup, schedule_sticker_cache_warmup
from telegram_credentials import (
    TelegramCredentials,
    get_default_credentials,
    get_effective_credentials,
    has_default_credentials,
    stored_credentials_match_default,
)

router = APIRouter(prefix="/settings", tags=["Налаштування"])
_auto_group_sync_lock = asyncio.Lock()


async def _sync_groups_after_auth():
    if _auto_group_sync_lock.locked():
        log_event("INFO", "Groups", "Автосинхронізація груп уже виконується")
        return

    async with _auto_group_sync_lock:
        db = SessionLocal()
        try:
            result = await sync_telegram_groups(db)
            log_event("INFO", "Groups", f"Автосинхронізація після входу завершена: додано {result.get('added_count', 0)}")
        except Exception as error:
            db.rollback()
            detail = getattr(error, "detail", str(error))
            log_event("WARNING", "Groups", f"Автосинхронізація після входу не вдалася: {detail}")
        finally:
            db.close()


def _queue_groups_sync_after_auth(background_tasks: BackgroundTasks):
    background_tasks.add_task(_sync_groups_after_auth)


async def _start_sticker_warmup_after_auth():
    schedule_sticker_cache_warmup(reason="auth")


def _queue_sticker_warmup_after_auth(background_tasks: BackgroundTasks):
    background_tasks.add_task(_start_sticker_warmup_after_auth)


def _get_or_create_settings(db: Session) -> BotSettings:
    db_settings = db.query(BotSettings).first()
    if not db_settings:
        db_settings = BotSettings()
        db.add(db_settings)
        db.flush()
    return db_settings


def _apply_custom_credentials(db_settings: BotSettings, api_id: str | None, api_hash: str | None):
    api_id = (api_id or "").strip()
    api_hash = (api_hash or "").strip()

    if not api_id and not api_hash:
        return
    if not api_id or not api_hash:
        raise HTTPException(status_code=400, detail="API ID та API Hash потрібно вводити разом")

    try:
        int(api_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="API ID має бути числом") from error

    db_settings.api_id = api_id
    db_settings.api_hash = api_hash


def _parse_custom_credentials(api_id: str | None, api_hash: str | None) -> TelegramCredentials | None:
    api_id = (api_id or "").strip()
    api_hash = (api_hash or "").strip()

    if not api_id and not api_hash:
        return None
    if not api_id or not api_hash:
        raise HTTPException(status_code=400, detail={
            "message": "API ID та API Hash потрібно вводити разом.",
            "code": "API_CREDENTIALS_INCOMPLETE",
        })

    try:
        numeric_api_id = int(api_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={
            "message": "API ID має бути числом.",
            "code": "API_ID_NOT_NUMERIC",
        }) from error

    return TelegramCredentials(api_id=numeric_api_id, api_hash=api_hash, source="custom")


def _clear_custom_credentials(db: Session, settings: BotSettings | None, commit: bool = True):
    if not settings:
        return
    settings.api_id = None
    settings.api_hash = None
    if commit:
        db.commit()
        db.refresh(settings)


def _friendly_auth_error(error: str | None, code: str | None = None) -> tuple[str, str | None]:
    text = str(error or "")
    detected_code = code or ("API_ID_INVALID" if "API_ID_INVALID" in text.upper() else None)
    if detected_code == "API_ID_INVALID":
        return (
            "Невірний API ID або API Hash. Власні API-дані скинуто, можна спробувати вхід ще раз із вбудованим ключем додатку.",
            detected_code,
        )
    return text or "Помилка авторизації Telegram", detected_code


def _raise_auth_result_error(result: dict, fallback: str = "Помилка авторизації Telegram"):
    message, code = _friendly_auth_error(result.get("error") or fallback, result.get("code"))
    raise HTTPException(status_code=400, detail={"message": message, "code": code})


def _resolve_auth_credentials(
    settings: BotSettings | None,
    api_id: str | None,
    api_hash: str | None,
) -> tuple[TelegramCredentials, bool]:
    custom_credentials = _parse_custom_credentials(api_id, api_hash)
    if custom_credentials:
        return custom_credentials, True
    return get_effective_credentials(settings), False


def _save_successful_custom_credentials(db: Session, settings: BotSettings, credentials: TelegramCredentials, requested_custom: bool):
    if not requested_custom or credentials.source != "custom":
        return
    settings.api_id = str(credentials.api_id)
    settings.api_hash = credentials.api_hash
    db.commit()
    db.refresh(settings)


def _safe_settings_response(settings: BotSettings | None, user_info=None):
    has_custom_credentials = bool(settings and settings.api_id and settings.api_hash)
    return {
        "id": settings.id if settings else None,
        "token": settings.token if settings else None,
        "api_id": settings.api_id if has_custom_credentials else "",
        "api_hash": "",
        "api_hash_set": has_custom_credentials,
        "credentials_mode": "custom" if has_custom_credentials else "built_in",
        "has_builtin_credentials": has_default_credentials(),
        "phone": settings.phone if settings else "",
        "is_connected": pyrogram_manager.is_connected,
        "has_session": pyrogram_manager.has_session(),
        "manually_disconnected": pyrogram_manager.manually_disconnected,
        "user_info": user_info,
        "windows_notifications_enabled": bool(getattr(settings, "windows_notifications_enabled", 1)) if settings else True,
    }


def _credentials_or_error(settings: BotSettings | None):
    try:
        return get_effective_credentials(settings)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Збережений API ID має бути числом") from error


async def _connect_saved_session_if_possible(settings: BotSettings | None):
    if pyrogram_manager.is_connected:
        return
    if pyrogram_manager.manually_disconnected or not pyrogram_manager.has_session():
        return

    try:
        credentials = get_effective_credentials(settings)
    except Exception as error:
        log_event("WARNING", "Pyrogram", f"Не вдалося відновити Telegram-сесію: {error}")
        return

    try:
        connected = await pyrogram_manager.connect_with_session(credentials.api_id, credentials.api_hash)
        if (
            not connected
            and credentials.source == "custom"
            and pyrogram_manager.last_error_code == "API_ID_INVALID"
            and has_default_credentials()
        ):
            db = SessionLocal()
            try:
                fresh_settings = db.query(BotSettings).first()
                _clear_custom_credentials(db, fresh_settings)
            finally:
                db.close()
            credentials = get_default_credentials()
            connected = await pyrogram_manager.connect_with_session(credentials.api_id, credentials.api_hash)
        if connected:
            schedule_sticker_cache_warmup(reason="session-restore")
        if connected:
            log_event("INFO", "Pyrogram", "Telegram-сесію відновлено автоматично")
    except Exception as error:
        log_event("WARNING", "Pyrogram", f"Автовідновлення Telegram-сесії не вдалося: {error}")


def _clear_redundant_builtin_credentials(db: Session, settings: BotSettings | None):
    if settings and stored_credentials_match_default(settings):
        settings.api_id = None
        settings.api_hash = None
        db.commit()
        db.refresh(settings)


@router.get("/bot")
async def get_bot_settings(db: Session = Depends(get_db)):
    """Отримати налаштування + статус підключення Pyrogram"""
    settings = db.query(BotSettings).first()
    _clear_redundant_builtin_credentials(db, settings)
    await _connect_saved_session_if_possible(settings)
    if settings:
        db.refresh(settings)
    
    # Отримуємо інфо про користувача якщо підключений
    user_info = None
    if pyrogram_manager.is_connected:
        user_info = await pyrogram_manager.get_user_info()
    
    return _safe_settings_response(settings, user_info)


@router.post("/bot")
async def save_bot_settings(settings: BotSettingsCreate, db: Session = Depends(get_db)):
    """Зберегти credentials для Pyrogram (api_id, api_hash, phone)"""
    db_settings = _get_or_create_settings(db)
    _clear_redundant_builtin_credentials(db, db_settings)

    api_id = (settings.api_id or "").strip()
    api_hash = (settings.api_hash or "").strip()
    if api_id or api_hash:
        _apply_custom_credentials(db_settings, api_id, api_hash)
    else:
        db_settings.api_id = None
        db_settings.api_hash = None

    if settings.phone is not None:
        db_settings.phone = settings.phone.strip()
    
    db.commit()
    db.refresh(db_settings)
    
    return {"message": "Налаштування збережено", **_safe_settings_response(db_settings)}


@router.post("/auth/send-code")
async def send_auth_code(req: SendCodeRequest, db: Session = Depends(get_db)):
    """Крок 1: Відправити SMS-код на номер телефону"""
    phone = (req.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="Введіть номер телефону")
    
    db_settings = _get_or_create_settings(db)
    _clear_redundant_builtin_credentials(db, db_settings)
    credentials, requested_custom = _resolve_auth_credentials(db_settings, req.api_id, req.api_hash)
    db_settings.phone = phone
    db.commit()
    db.refresh(db_settings)
    
    result = await pyrogram_manager.send_code(credentials.api_id, credentials.api_hash, phone)

    if (
        not result["ok"]
        and (result.get("code") == "API_ID_INVALID" or "API_ID_INVALID" in str(result.get("error", "")).upper())
        and credentials.source == "custom"
    ):
        _clear_custom_credentials(db, db_settings)
        if not requested_custom and has_default_credentials():
            credentials = get_default_credentials()
            result = await pyrogram_manager.send_code(credentials.api_id, credentials.api_hash, phone)
    
    if not result["ok"]:
        _raise_auth_result_error(result, "Не вдалося відправити код")

    _save_successful_custom_credentials(db, db_settings, credentials, requested_custom)
    
    return {"message": "Код відправлено на ваш Telegram", "ok": True}


@router.post("/auth/verify-code")
async def verify_auth_code(req: VerifyCodeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Крок 2: Підтвердити SMS-код"""
    result = await pyrogram_manager.verify_code(req.phone, req.code)
    
    if not result["ok"]:
        if result.get("needs_2fa"):
            return {"ok": False, "needs_2fa": True, "message": "Потрібен пароль двофакторної аутентифікації"}
        raise HTTPException(status_code=400, detail=result["error"])
    
    _queue_groups_sync_after_auth(background_tasks)
    _queue_sticker_warmup_after_auth(background_tasks)
    return {"ok": True, "user": result["user"], "message": "Авторизація успішна!", "groups_sync_queued": True}


@router.post("/auth/verify-2fa")
async def verify_2fa(req: Verify2FARequest, background_tasks: BackgroundTasks):
    """Крок 3 (опціонально): Ввести пароль 2FA"""
    result = await pyrogram_manager.verify_2fa(req.password)
    
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    
    _queue_groups_sync_after_auth(background_tasks)
    _queue_sticker_warmup_after_auth(background_tasks)
    return {"ok": True, "user": result["user"], "message": "Авторизація успішна!", "groups_sync_queued": True}


@router.post("/auth/logout")
async def logout():
    """Тимчасово від'єднати Telegram без видалення збереженої сесії."""
    cancel_sticker_cache_warmup()
    await pyrogram_manager.disconnect(manual=True)
    return {
        "message": "Telegram від'єднано до перезапуску програми",
        "is_connected": False,
        "has_session": pyrogram_manager.has_session(),
        "manually_disconnected": pyrogram_manager.manually_disconnected,
    }


@router.post("/auth/reconnect")
async def reconnect(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Підключити збережену Telegram-сесію після ручного від'єднання."""
    if not pyrogram_manager.has_session():
        raise HTTPException(status_code=400, detail="Збережену Telegram-сесію не знайдено. Увійдіть заново.")

    settings = db.query(BotSettings).first()
    pyrogram_manager.allow_reconnect()
    await _connect_saved_session_if_possible(settings)

    user_info = None
    if pyrogram_manager.is_connected:
        user_info = await pyrogram_manager.get_user_info()
        _queue_sticker_warmup_after_auth(background_tasks)

    return {
        "ok": pyrogram_manager.is_connected,
        "message": "Telegram підключено" if pyrogram_manager.is_connected else "Не вдалося підключити збережену Telegram-сесію",
        **_safe_settings_response(settings, user_info),
    }


@router.post("/auth/logout-full")
async def logout_full():
    """Повністю вийти з Telegram і видалити тільки дані авторизації."""
    cancel_sticker_cache_warmup()
    await pyrogram_manager.logout_full()
    return {"message": "Telegram акаунт від'єднано повністю. Бази, шаблони й файли залишилися."}


@router.get("/auth/status")
async def auth_status(db: Session = Depends(get_db)):
    """Перевірити статус авторизації"""
    settings = db.query(BotSettings).first()
    await _connect_saved_session_if_possible(settings)

    connected = pyrogram_manager.is_connected
    user_info = None
    if connected:
        user_info = await pyrogram_manager.get_user_info()
    
    return {
        "is_connected": connected,
        "has_session": pyrogram_manager.has_session(),
        "manually_disconnected": pyrogram_manager.manually_disconnected,
        "user_info": user_info
    }


@router.post("/auth/qr")
async def get_qr_code(req: QRLoginRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """QR-код авторизація: генерує QR-зображення для сканування"""
    
    db_settings = _get_or_create_settings(db)
    _clear_redundant_builtin_credentials(db, db_settings)
    credentials, requested_custom = _resolve_auth_credentials(db_settings, req.api_id, req.api_hash)
    if req.phone is not None:
        db_settings.phone = req.phone.strip()
    db.commit()
    db.refresh(db_settings)
    
    result = await pyrogram_manager.export_qr_token(credentials.api_id, credentials.api_hash)

    if (
        not result["ok"]
        and (result.get("code") == "API_ID_INVALID" or "API_ID_INVALID" in str(result.get("error", "")).upper())
        and credentials.source == "custom"
    ):
        _clear_custom_credentials(db, db_settings)
        if not requested_custom and has_default_credentials():
            credentials = get_default_credentials()
            result = await pyrogram_manager.export_qr_token(credentials.api_id, credentials.api_hash)
    
    if not result["ok"]:
        _raise_auth_result_error(result, "Не вдалося створити QR-код")

    _save_successful_custom_credentials(db, db_settings, credentials, requested_custom)
    
    # Якщо вже авторизовано
    if result.get("authorized"):
        _queue_groups_sync_after_auth(background_tasks)
        _queue_sticker_warmup_after_auth(background_tasks)
        result["groups_sync_queued"] = True
        return result
    
    return result


@router.post("/auth/qr/check")
async def check_qr_code(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Перевіряє чи користувач просканував QR-код"""
    db_settings = db.query(BotSettings).first()
    _clear_redundant_builtin_credentials(db, db_settings)
    credentials = _credentials_or_error(db_settings)
    
    result = await pyrogram_manager.check_qr_status(credentials.api_id, credentials.api_hash)

    if (
        not result["ok"]
        and (result.get("code") == "API_ID_INVALID" or "API_ID_INVALID" in str(result.get("error", "")).upper())
        and credentials.source == "custom"
    ):
        _clear_custom_credentials(db, db_settings)
        credentials = get_default_credentials()
        result = await pyrogram_manager.check_qr_status(credentials.api_id, credentials.api_hash)
    
    if not result["ok"]:
        _raise_auth_result_error(result, "Помилка перевірки QR-коду")

    if result.get("authorized"):
        _queue_groups_sync_after_auth(background_tasks)
        _queue_sticker_warmup_after_auth(background_tasks)
        result["groups_sync_queued"] = True
    
    return result


@router.post("/auth/credentials/reset")
async def reset_auth_credentials(db: Session = Depends(get_db)):
    """Скинути власні Telegram API ID/API Hash і повернутися до вбудованого ключа додатку."""
    settings = _get_or_create_settings(db)
    _clear_custom_credentials(db, settings)
    user_info = await pyrogram_manager.get_user_info() if pyrogram_manager.is_connected else None
    return {
        "message": "Власні API-дані скинуто. Буде використано вбудований ключ додатку.",
        **_safe_settings_response(settings, user_info),
    }
