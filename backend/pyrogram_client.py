# Менеджер Pyrogram клієнта — singleton для всього додатку
import os
import asyncio
import base64
import io
import shutil
import time
from pyrogram import Client, raw
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, 
    PhoneCodeExpired, PasswordHashInvalid,
    FloodWait, RPCError,
    AuthKeyDuplicated, AuthKeyInvalid, AuthKeyUnregistered,
    SessionExpired, SessionRevoked, Unauthorized,
    UserDeactivated, UserDeactivatedBan
)
import qrcode

import sys
import platform
from logger import log_event
from app_paths import get_app_data_dir

def _user_data_dir() -> str:
    return get_app_data_dir()


def _install_session_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _legacy_session_dirs() -> list[str]:
    candidates = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "SchoolManager"))
    if sys.platform == "darwin":
        candidates.append(os.path.join(os.path.expanduser("~"), ".school_manager"))
    candidates.append(_install_session_dir())

    seen = set()
    result = []
    current_dir = os.path.abspath(SESSION_DIR)
    for path in candidates:
        abs_path = os.path.abspath(path)
        if abs_path == current_dir or abs_path in seen:
            continue
        seen.add(abs_path)
        result.append(path)
    return result


def _session_files(session_name: str):
    return [
        f"{session_name}.session",
        f"{session_name}.session-journal",
        f"{session_name}.session-wal",
        f"{session_name}.session-shm",
    ]


SESSION_DIR = _user_data_dir()
SESSION_NAME = os.path.join(SESSION_DIR, "user_session")


def _primary_session_files() -> list[str]:
    session_names = [SESSION_NAME]
    for legacy_dir in _legacy_session_dirs():
        session_names.append(os.path.join(legacy_dir, "user_session"))
    return [f"{session_name}.session" for session_name in session_names]


def _all_session_files() -> list[str]:
    session_names = [SESSION_NAME]
    for legacy_dir in _legacy_session_dirs():
        session_names.append(os.path.join(legacy_dir, "user_session"))

    files = []
    seen = set()
    for session_name in session_names:
        for path in _session_files(session_name):
            abs_path = os.path.abspath(path)
            if abs_path in seen:
                continue
            seen.add(abs_path)
            files.append(path)
    return files


def _delete_saved_session_files() -> int:
    removed = 0
    for path in _all_session_files():
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            pass
        except OSError as error:
            log_event("WARNING", "Pyrogram", f"Не вдалося видалити файл сесії {path}: {error}")
    return removed


def migrate_legacy_session():
    os.makedirs(SESSION_DIR, exist_ok=True)
    current_session = f"{SESSION_NAME}.session"
    if os.path.exists(current_session):
        return

    for legacy_dir in _legacy_session_dirs():
        legacy_session_name = os.path.join(legacy_dir, "user_session")
        legacy_session = f"{legacy_session_name}.session"
        if not os.path.exists(legacy_session):
            continue

        try:
            for source in _session_files(legacy_session_name):
                if os.path.exists(source):
                    target = os.path.join(SESSION_DIR, os.path.basename(source))
                    if not os.path.exists(target):
                        shutil.copy2(source, target)

            if getattr(sys, "frozen", False) and os.path.abspath(legacy_dir) == os.path.abspath(_install_session_dir()):
                for source in _session_files(legacy_session_name):
                    try:
                        if os.path.exists(source):
                            os.remove(source)
                    except OSError:
                        pass

            print(f"[Pyrogram] Session migrated to {SESSION_DIR}")
            return
        except Exception as error:
            print(f"[Pyrogram] Session migration failed: {error}")


migrate_legacy_session()


def get_telegram_error_code(error) -> str | None:
    text = str(error or "").upper()
    for code in (
        "API_ID_INVALID",
        "API_HASH_INVALID",
        "PHONE_NUMBER_INVALID",
        "PHONE_CODE_INVALID",
        "PHONE_CODE_EXPIRED",
        "PASSWORD_HASH_INVALID",
        "FLOOD_WAIT",
    ):
        if code in text:
            return code
    return None


class PyrogramManager:
    """
    Singleton менеджер Pyrogram клієнта.
    Відповідає за підключення, авторизацію та доступ до клієнта.
    """
    
    _instance = None
    _client: Client = None
    _is_connected: bool = False
    _phone_code_hash: str = None  # Хеш для верифікації SMS-коду
    _manual_disconnect: bool = False
    _connect_lock: asyncio.Lock = None
    _dialog_warmup_lock: asyncio.Lock = None
    _dialog_warmup_task: asyncio.Task | None = None
    _last_dialog_warmup_at: float = 0
    _last_error_code: str | None = None
    _api_id: int | None = None
    _api_hash: str | None = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_connect_lock(self) -> asyncio.Lock:
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        return self._connect_lock

    def _get_dialog_warmup_lock(self) -> asyncio.Lock:
        if self._dialog_warmup_lock is None:
            self._dialog_warmup_lock = asyncio.Lock()
        return self._dialog_warmup_lock
    
    @property
    def client(self) -> Client:
        return self._client
    
    @property
    def is_connected(self) -> bool:
        if not self._is_connected or self._client is None:
            return False
        return bool(getattr(self._client, "is_connected", True))

    @property
    def manually_disconnected(self) -> bool:
        return self._manual_disconnect

    @property
    def last_error_code(self) -> str | None:
        return self._last_error_code

    def allow_reconnect(self):
        self._manual_disconnect = False

    def _credentials_match(self, api_id: int, api_hash: str) -> bool:
        return self._api_id == int(api_id) and self._api_hash == api_hash

    async def _cache_current_user(self):
        me = await self._client.get_me()
        self._client.me = me
        return me

    def _cancel_dialog_warmup(self):
        task = self._dialog_warmup_task
        if task and not task.done():
            task.cancel()
        self._dialog_warmup_task = None

    async def _warm_dialogs(self, limit: int = 500):
        try:
            await asyncio.sleep(2)
            await self.warm_dialogs_now(limit=limit, min_interval=30)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log_event("WARNING", "Pyrogram", f"Фонове оновлення діалогів не вдалося: {error}")

    def _schedule_dialog_warmup(self):
        task = self._dialog_warmup_task
        if task and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._dialog_warmup_task = loop.create_task(self._warm_dialogs())

    async def warm_dialogs_now(self, limit: int = 1000, min_interval: int = 10) -> bool:
        """
        Оновлює Pyrogram peer-cache діалогів синхронно.
        Це потрібно після рестарту, коли числові id каналів `-100...`
        ще не мають access_hash у локальній сесії.
        """
        client = self._client
        if not client or not self.is_connected:
            return False

        async with self._get_dialog_warmup_lock():
            now = time.monotonic()
            if min_interval and self._last_dialog_warmup_at and now - self._last_dialog_warmup_at < min_interval:
                return True

            count = 0
            async for _ in client.get_dialogs(limit=limit):
                count += 1
            self._last_dialog_warmup_at = time.monotonic()
            if count:
                log_event("INFO", "Pyrogram", f"Оновлено Telegram peer-cache: {count} діалогів")
            return True
    
    def has_session(self) -> bool:
        """Перевіряє чи існує збережена сесія"""
        return any(os.path.exists(path) for path in _primary_session_files())

    async def _stop_client_safely(self):
        self._cancel_dialog_warmup()
        if not self._client:
            return

        try:
            if getattr(self._client, "is_initialized", False):
                await self._client.stop()
            elif getattr(self._client, "is_connected", False):
                await self._client.disconnect()
        except Exception:
            pass
    
    async def initialize(self, api_id: int, api_hash: str):
        """Ініціалізує клієнт з credentials (без підключення)"""
        self._manual_disconnect = False
        self._last_error_code = None
        self._cancel_dialog_warmup()
        if self._client:
            try:
                await self._stop_client_safely()
            except Exception:
                pass
        
        self._client = Client(
            SESSION_NAME,
            api_id=api_id,
            api_hash=api_hash,
            device_model="School Manager",
            app_version="2.3",
            system_version=platform.system() or sys.platform
        )
        self._api_id = int(api_id)
        self._api_hash = api_hash
        self._is_connected = False
    
    async def connect_with_session(self, api_id: int, api_hash: str) -> bool:
        """
        Спроба підключитися з існуючою сесією.
        Повертає True якщо успішно, False якщо сесії немає або вона недійсна.
        """
        async with self._get_connect_lock():
            return await self._connect_with_session_unlocked(api_id, api_hash)

    async def _connect_with_session_unlocked(self, api_id: int, api_hash: str) -> bool:
        self._last_error_code = None
        if self.is_connected:
            return True

        if self._manual_disconnect:
            return False

        if not self.has_session():
            return False
        
        try:
            await self.initialize(api_id, api_hash)
            is_authorized = await self._client.connect()
            if not is_authorized:
                log_event("WARNING", "Pyrogram", "Збережена Telegram-сесія не авторизована. Потрібен новий вхід.")
                await self._stop_client_safely()
                removed = _delete_saved_session_files()
                log_event("INFO", "Pyrogram", f"Неавторизовану Telegram-сесію видалено. Файлів: {removed}")
                self._client = None
                self._is_connected = False
                return False

            self._is_connected = True
            self._manual_disconnect = False
            await self._client.invoke(raw.functions.updates.GetState())
            me = await self._cache_current_user()
            if not self._client.is_initialized:
                await self._client.initialize()

            log_event("INFO", "Pyrogram", f"Підключено як: {me.first_name} (@{me.username or 'без username'})")
            self._schedule_dialog_warmup()
                
            return True
        except (
            AuthKeyDuplicated, AuthKeyInvalid, AuthKeyUnregistered,
            SessionExpired, SessionRevoked, Unauthorized,
            UserDeactivated, UserDeactivatedBan
        ) as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("WARNING", "Pyrogram", f"Telegram-сесія недійсна і буде видалена: {e}")
            await self._stop_client_safely()
            removed = _delete_saved_session_files()
            log_event("INFO", "Pyrogram", f"Недійсну Telegram-сесію видалено. Файлів: {removed}")
            self._client = None
            self._is_connected = False
            return False
        except Exception as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("ERROR", "Pyrogram", f"Помилка підключення з сесією: {e}")
            await self._stop_client_safely()
            self._client = None
            self._is_connected = False
            return False
    
    async def send_code(self, api_id: int, api_hash: str, phone: str) -> dict:
        """
        Крок 1 авторизації: відправляє SMS-код на номер телефону.
        Повертає: {ok: bool, needs_2fa: bool, error: str}
        """
        try:
            await self.initialize(api_id, api_hash)
            await self._client.connect()
            
            sent_code = await self._client.send_code(phone)
            self._phone_code_hash = sent_code.phone_code_hash
            
            log_event("INFO", "Pyrogram", f"Код відправлено на {phone}")
            return {"ok": True, "phone_code_hash": self._phone_code_hash}
            
        except FloodWait as e:
            self._last_error_code = "FLOOD_WAIT"
            log_event("WARNING", "Pyrogram", f"FloodWait: зачекайте {e.value}с")
            return {"ok": False, "error": f"Telegram просить зачекати {e.value} секунд перед повторною спробою", "code": "FLOOD_WAIT"}
        except RPCError as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("ERROR", "Pyrogram", f"RPC Error: {e}")
            return {"ok": False, "error": str(e), "code": self._last_error_code}
        except Exception as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("ERROR", "Pyrogram", f"Помилка: {e}")
            return {"ok": False, "error": str(e), "code": self._last_error_code}
    
    async def verify_code(self, phone: str, code: str) -> dict:
        """
        Крок 2 авторизації: підтверджує SMS-код.
        Повертає: {ok: bool, needs_2fa: bool, error: str}
        """
        if not self._client or not self._phone_code_hash:
            return {"ok": False, "error": "Спочатку запросіть код"}
        
        try:
            await self._client.sign_in(phone, self._phone_code_hash, code)
            self._is_connected = True
            me = await self._cache_current_user()
            log_event("INFO", "Pyrogram", f"Авторизовано як: {me.first_name}")
            return {
                "ok": True, 
                "user": {
                    "name": f"{me.first_name} {me.last_name or ''}".strip(),
                    "username": me.username,
                    "phone": me.phone_number
                }
            }
            
        except SessionPasswordNeeded:
            # Потрібен пароль 2FA
            log_event("WARNING", "Pyrogram", "Потрібен пароль двофакторної аутентифікації")
            return {"ok": False, "needs_2fa": True, "error": "Потрібен пароль 2FA"}
            
        except PhoneCodeInvalid:
            return {"ok": False, "error": "Невірний код. Спробуйте ще раз."}
            
        except PhoneCodeExpired:
            return {"ok": False, "error": "Код застарів. Запросіть новий."}
            
        except FloodWait as e:
            return {"ok": False, "error": f"Зачекайте {e.value} секунд"}
            
        except Exception as e:
            log_event("ERROR", "Pyrogram", f"Помилка верифікації: {e}")
            return {"ok": False, "error": str(e)}
    
    async def verify_2fa(self, password: str) -> dict:
        """
        Крок 3 (опціонально): ввід пароля 2FA.
        """
        if not self._client:
            return {"ok": False, "error": "Клієнт не ініціалізовано"}
        
        try:
            await self._client.check_password(password)
            self._is_connected = True
            me = await self._cache_current_user()
            log_event("INFO", "Pyrogram", f"2FA пройдено: {me.first_name}")
            return {
                "ok": True,
                "user": {
                    "name": f"{me.first_name} {me.last_name or ''}".strip(),
                    "username": me.username,
                    "phone": me.phone_number
                }
            }
        except PasswordHashInvalid:
            return {"ok": False, "error": "Невірний пароль 2FA"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    async def export_qr_token(self, api_id: int, api_hash: str) -> dict:
        """
        QR-код авторизація: генерує токен і повертає QR-зображення (base64 PNG).
        Користувач сканує QR в Telegram → Налаштування → Пристрої → Сканувати QR-код.
        """
        try:
            # Ініціалізуємо клієнт якщо потрібно
            self._last_error_code = None
            if not self._client or not self._credentials_match(api_id, api_hash):
                await self.initialize(api_id, api_hash)
            
            if not self._client.is_connected:
                await self._client.connect()
            
            # Запитуємо токен для QR через raw API
            result = await self._client.invoke(
                raw.functions.auth.ExportLoginToken(
                    api_id=api_id,
                    api_hash=api_hash,
                    except_ids=[]
                )
            )
            
            if isinstance(result, raw.types.auth.LoginToken):
                # Формуємо URL для QR-коду
                token_base64 = base64.urlsafe_b64encode(result.token).decode().rstrip('=')
                qr_url = f"tg://login?token={token_base64}"
                
                # Генеруємо QR-зображення
                qr = qrcode.QRCode(version=1, box_size=8, border=2)
                qr.add_data(qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#ffffff", back_color="#1e293b")
                
                # Конвертуємо в base64 PNG
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                qr_base64 = base64.b64encode(buffer.getvalue()).decode()
                
                log_event("INFO", "Pyrogram", f"QR-код згенеровано (expires: {result.expires}с)")
                return {
                    "ok": True, 
                    "qr_image": f"data:image/png;base64,{qr_base64}",
                    "expires": result.expires
                }
            
            elif isinstance(result, raw.types.auth.LoginTokenSuccess):
                # Вже авторизовано (наприклад, повторний запит після сканування)
                self._is_connected = True
                await self._client.storage.user_id(result.authorization.user.id)
                await self._client.storage.is_bot(False)
                me = await self._cache_current_user()
                log_event("INFO", "Pyrogram", f"QR авторизація успішна: {me.first_name}")
                return {
                    "ok": True, 
                    "authorized": True,
                    "user": {
                        "name": f"{me.first_name} {me.last_name or ''}".strip(),
                        "username": me.username,
                        "phone": me.phone_number
                    }
                }
            
            elif isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                # Потрібна міграція на інший DC
                log_event("WARNING", "Pyrogram", f"Міграція на DC {result.dc_id}")
                return {"ok": False, "error": "Потрібна міграція DC. Спробуйте SMS авторизацію."}
            
            return {"ok": False, "error": "Невідомий тип відповіді"}
            
        except FloodWait as e:
            self._last_error_code = "FLOOD_WAIT"
            return {"ok": False, "error": f"Зачекайте {e.value} секунд", "code": "FLOOD_WAIT"}
        except RPCError as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("ERROR", "Pyrogram", f"QR RPC Error: {e}")
            return {"ok": False, "error": str(e), "code": self._last_error_code}
        except Exception as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("ERROR", "Pyrogram", f"QR помилка: {e}")
            return {"ok": False, "error": str(e), "code": self._last_error_code}
    
    async def check_qr_status(self, api_id: int, api_hash: str) -> dict:
        """
        Перевіряє чи користувач просканував QR-код.
        Повертає: {ok, authorized, needs_2fa, qr_image (новий QR якщо старий протух)}
        """
        try:
            self._last_error_code = None
            if not self._client or not self._credentials_match(api_id, api_hash):
                await self.initialize(api_id, api_hash)
            if not self._client.is_connected:
                await self._client.connect()
            
            result = await self._client.invoke(
                raw.functions.auth.ExportLoginToken(
                    api_id=api_id,
                    api_hash=api_hash,
                    except_ids=[]
                )
            )
            
            if isinstance(result, raw.types.auth.LoginTokenSuccess):
                # Користувач просканував QR! Авторизація успішна
                self._is_connected = True
                
                # Зберігаємо дані авторизації
                user = result.authorization.user
                await self._client.storage.user_id(user.id)
                await self._client.storage.is_bot(False)
                
                me = await self._cache_current_user()
                log_event("INFO", "Pyrogram", f"QR авторизація: {me.first_name}")
                return {
                    "ok": True,
                    "authorized": True,
                    "user": {
                        "name": f"{me.first_name} {me.last_name or ''}".strip(),
                        "username": me.username,
                        "phone": me.phone_number
                    }
                }
            
            elif isinstance(result, raw.types.auth.LoginToken):
                # Ще не просканували — повертаємо оновлений QR
                token_base64 = base64.urlsafe_b64encode(result.token).decode().rstrip('=')
                qr_url = f"tg://login?token={token_base64}"
                
                qr = qrcode.QRCode(version=1, box_size=8, border=2)
                qr.add_data(qr_url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#ffffff", back_color="#1e293b")
                
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                qr_base64 = base64.b64encode(buffer.getvalue()).decode()
                
                return {
                    "ok": True, 
                    "authorized": False,
                    "qr_image": f"data:image/png;base64,{qr_base64}",
                    "expires": result.expires
                }
            
            elif isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                return {"ok": False, "error": "Потрібна міграція DC. Спробуйте SMS."}
            
            return {"ok": True, "authorized": False}
            
        except SessionPasswordNeeded:
            log_event("WARNING", "Pyrogram", "QR: потрібен 2FA пароль")
            return {"ok": True, "authorized": False, "needs_2fa": True}
        except FloodWait as e:
            self._last_error_code = "FLOOD_WAIT"
            return {"ok": False, "error": f"Зачекайте {e.value} секунд", "code": "FLOOD_WAIT"}
        except Exception as e:
            self._last_error_code = get_telegram_error_code(e)
            log_event("ERROR", "Pyrogram", f"QR check error: {e}")
            return {"ok": False, "error": str(e), "code": self._last_error_code}

    async def disconnect(self, manual: bool = False):
        """Від'єднатися"""
        if manual:
            self._manual_disconnect = True
        if self._client:
            await self._stop_client_safely()
            self._is_connected = False
            message = "Від'єднано до перезапуску програми" if manual else "Від'єднано"
            log_event("INFO", "Pyrogram", message)
    
    async def logout(self):
        """Повний вихід — видаляє сесію"""
        await self.logout_full()

    async def logout_full(self):
        """Повний вихід — завершує Telegram-сесію і видаляє тільки дані авторизації."""
        if self._client:
            try:
                if not self._client.is_connected:
                    await self._client.connect()
                await self._client.log_out()
                log_event("INFO", "Pyrogram", "Telegram-сесію завершено на сервері")
            except Exception as error:
                log_event("WARNING", "Pyrogram", f"Не вдалося завершити Telegram-сесію на сервері: {error}")
            finally:
                await self._stop_client_safely()

        self._is_connected = False
        self._client = None
        self._phone_code_hash = None
        self._manual_disconnect = True

        removed = _delete_saved_session_files()
        log_event("INFO", "Pyrogram", f"Дані авторизації Telegram видалено. Файлів сесії: {removed}")
    
    async def get_user_info(self) -> dict:
        """Отримати інформацію про поточного користувача"""
        if not self.is_connected:
            return None
        try:
            me = getattr(self._client, "me", None)
            if me is None:
                me = await self._cache_current_user()
            return {
                "name": f"{me.first_name} {me.last_name or ''}".strip(),
                "username": me.username,
                "phone": me.phone_number
            }
        except Exception:
            return None


# Глобальний екземпляр менеджера
pyrogram_manager = PyrogramManager()
