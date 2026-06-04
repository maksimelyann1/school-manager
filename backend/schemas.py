# Pydantic схеми для валідації даних
from pydantic import BaseModel, Field
from typing import Optional, List


# === Схеми для категорій ===
class CategoryBase(BaseModel):
    """Базова схема категорії"""
    name: str


class CategoryCreate(CategoryBase):
    """Схема для створення категорії"""
    pass


class CategoryResponse(CategoryBase):
    """Схема відповіді з категорією"""
    id: int

    class Config:
        from_attributes = True


# === Схеми для груп ===
class GroupBase(BaseModel):
    """Базова схема групи"""
    name: str
    telegram_id: str
    lesson_time: Optional[str] = None
    lesson_day: Optional[str] = None
    category_id: Optional[int] = None


class GroupCreate(GroupBase):
    """Схема для створення групи"""
    pass


class GroupBulkCategoryUpdate(BaseModel):
    """Схема для масового перенесення груп між категоріями"""
    group_ids: List[int] = Field(default_factory=list)
    category_id: Optional[int] = None


class GroupResponse(GroupBase):
    """Схема відповіді з групою"""
    id: int
    category_name: Optional[str] = None
    
    class Config:
        from_attributes = True


# === Схеми для налаштувань ===
class BotSettingsBase(BaseModel):
    """Базова схема налаштувань"""
    token: Optional[str] = None
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    phone: Optional[str] = None


class BotSettingsCreate(BaseModel):
    """Схема для збереження налаштувань Pyrogram"""
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    phone: Optional[str] = None


class BotSettingsResponse(BotSettingsBase):
    """Схема відповіді з налаштуваннями"""
    id: int
    is_connected: Optional[bool] = False  # Чи підключений Pyrogram
    user_info: Optional[dict] = None      # Інфо про авторизованого користувача
    windows_notifications_enabled: Optional[bool] = True
    
    class Config:
        from_attributes = True


# === Схеми для авторизації Pyrogram ===
class SendCodeRequest(BaseModel):
    """Запит на відправку SMS-коду"""
    phone: str
    api_id: Optional[str] = None
    api_hash: Optional[str] = None


class QRLoginRequest(BaseModel):
    """Запит на QR-авторизацію"""
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    phone: Optional[str] = None


class VerifyCodeRequest(BaseModel):
    """Підтвердження SMS-коду"""
    phone: str
    code: str


class Verify2FARequest(BaseModel):
    """Підтвердження пароля 2FA"""
    password: str


# === Схеми для автоповідомлень ===
class AutoMessageBase(BaseModel):
    """Базова схема автоповідомлення"""
    group_id: int
    message: str
    send_time: str
    send_day: str
    repeat_count: int = 1


class AutoMessageCreate(AutoMessageBase):
    """Схема для створення автоповідомлення"""
    pass


class AutoMessageFileResponse(BaseModel):
    """Файл, прикріплений до автоповідомлення"""
    id: int
    original_filename: str
    stored_filename: str
    content_type: Optional[str] = None
    size: int = 0
    file_order: int = 0
    exists: bool = True

    class Config:
        from_attributes = True


class AutoMessageResponse(AutoMessageBase):
    """Схема відповіді з автоповідомленням"""
    id: int
    sent_count: int
    is_active: int
    source: str = "manual"
    parent_report_lesson_id: Optional[int] = None
    parent_report_run_id: Optional[int] = None
    scheduled_message_id: Optional[int] = None
    scheduled_target_at: Optional[str] = None
    metadata: Optional[dict] = None
    group: Optional[GroupResponse] = None
    files: List[AutoMessageFileResponse] = Field(default_factory=list)
    stickers: List[dict] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


# === Схема для відправки повідомлень ===
class SendMessageRequest(BaseModel):
    """Запит на відправку повідомлення"""
    group_ids: List[int]  # Список ID груп
    message: str  # Текст повідомлення


# === Схеми для шаблонів повідомлень ===
class TemplateBase(BaseModel):
    """Базова схема шаблону"""
    name: str
    text: str


class TemplateCreate(TemplateBase):
    """Схема для створення шаблону"""
    pass


class TemplateUpdate(TemplateBase):
    """Схема для оновлення шаблону"""
    pass


class TemplateFileResponse(BaseModel):
    """Файл, прикріплений до шаблону"""
    id: int
    original_filename: str
    stored_filename: str
    content_type: Optional[str] = None
    size: int = 0
    file_order: int = 0
    exists: bool = True

    class Config:
        from_attributes = True


class TemplateResponse(TemplateBase):
    """Схема відповіді з шаблоном"""
    id: int
    files: List[TemplateFileResponse] = Field(default_factory=list)
    stickers: List[dict] = Field(default_factory=list)

    class Config:
        from_attributes = True

# === Схеми для логів (Журнал подій) ===
class AppLogResponse(BaseModel):
    """Схема відповіді з логом"""
    id: int
    timestamp: str
    level: str
    module: str
    message: str

    class Config:
        from_attributes = True

# === Схеми для Дашборду ===
class UpcomingMessageResponse(BaseModel):
    id: int
    group_name: str
    message: str
    target_datetime: str  # ISO format string
    time_left: str  # Наприклад "через 2 години" або "сьогодні о 18:00"

class DashboardStatsResponse(BaseModel):
    is_connected: bool
    total_groups: int
    today_scheduled_count: int
    upcoming_messages: List[UpcomingMessageResponse]
