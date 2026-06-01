# Моделі бази даних
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from database import Base


class BotSettings(Base):
    """Налаштування Telegram (Pyrogram + Bot API)"""
    __tablename__ = "bot_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, nullable=True)       # Токен бота (опціонально, для зворотної сумісності)
    api_id = Column(String, nullable=True)       # API ID від my.telegram.org
    api_hash = Column(String, nullable=True)     # API Hash від my.telegram.org
    phone = Column(String, nullable=True)        # Номер телефону для Pyrogram
    windows_notifications_enabled = Column(Integer, default=1)


class Category(Base):
    """Категорія для групування груп (напр. місто Миронівка, місто Київ)"""
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Назва категорії
    
    # Зв'язок з групами
    groups = relationship("Group", back_populates="category")


class Group(Base):
    """Група в Telegram"""
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Назва групи (напр. "Фронтенд")
    telegram_id = Column(String, nullable=False)  # ID групи в Telegram
    lesson_time = Column(String, nullable=True)  # Час уроку (напр. "19:00")
    lesson_day = Column(String, nullable=True)  # День уроку (напр. "середа")
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)  # Категорія групи
    
    # Зв'язок з категорією
    category = relationship("Category", back_populates="groups")
    # Зв'язок з автоповідомленнями
    auto_messages = relationship("AutoMessage", back_populates="group", cascade="all, delete-orphan")


class AutoMessage(Base):
    """Автоматичне повідомлення (нагадування)"""
    __tablename__ = "auto_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    message = Column(String, nullable=False)  # Текст повідомлення
    send_time = Column(String, nullable=False)  # Час відправки (напр. "18:00")
    send_day = Column(String, nullable=False)  # День відправки (напр. "середа")
    repeat_count = Column(Integer, default=1)  # Кількість повторів (1 = один раз)
    sent_count = Column(Integer, default=0)  # Скільки разів вже відправлено
    is_active = Column(Integer, default=1)  # 1 = активне, 0 = вимкнене
    stickers = Column(Text, nullable=False, default="[]")  # JSON наліпок Telegram
    last_scheduled_for = Column(String, nullable=True)  # ISO час останнього Telegram-планування
    
    # Зв'язок з групою
    group = relationship("Group", back_populates="auto_messages")
    files = relationship("AutoMessageFile", back_populates="auto_message", cascade="all, delete-orphan")


class Template(Base):
    """Шаблон повідомлення для швидкого використання"""
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Назва шаблону (напр. "Посилання на Zoom")
    text = Column(Text, nullable=False)    # Текст шаблону
    stickers = Column(Text, nullable=False, default="[]")  # JSON наліпок Telegram
    files = relationship("TemplateFile", back_populates="template", cascade="all, delete-orphan")


class TemplateFile(Base):
    """Файл, прикріплений до шаблону повідомлення"""
    __tablename__ = "template_files"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=True)
    size = Column(Integer, default=0)
    file_order = Column(Integer, default=0)

    template = relationship("Template", back_populates="files")


class AutoMessageFile(Base):
    """Файл, прикріплений до автоповідомлення"""
    __tablename__ = "auto_message_files"

    id = Column(Integer, primary_key=True, index=True)
    auto_message_id = Column(Integer, ForeignKey("auto_messages.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False, unique=True)
    content_type = Column(String, nullable=True)
    size = Column(Integer, default=0)
    file_order = Column(Integer, default=0)

    auto_message = relationship("AutoMessage", back_populates="files")


class AppLog(Base):
    """Журнал подій та помилок додатку"""
    __tablename__ = "app_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String, nullable=False)  # Час події (ISO формат)
    level = Column(String, nullable=False)      # Рівень: INFO, WARNING, ERROR
    module = Column(String, nullable=False)     # Модуль: System, Pyrogram, AutoMsg
    message = Column(Text, nullable=False)      # Текст події


class ParentReportSettings(Base):
    """Налаштування вкладки 'Звіт батькам'"""
    __tablename__ = "parent_report_settings"

    id = Column(Integer, primary_key=True, index=True)
    spreadsheet_url = Column(Text, nullable=True)
    google_ai_api_key = Column(Text, nullable=True)
    google_ai_model = Column(String, nullable=False, default="gemini-2.5-flash")
    prompt_template = Column(Text, nullable=False, default="")
    auto_reports_enabled = Column(Integer, nullable=False, default=0)
    report_delay_minutes = Column(Integer, nullable=False, default=0)
    report_notifications_enabled = Column(Integer, nullable=False, default=1)
    report_notification_delay_minutes = Column(Integer, nullable=False, default=0)
    default_duration_minutes = Column(Integer, nullable=False, default=90)
    test_mode = Column(Integer, nullable=False, default=0)
    updated_at = Column(String, nullable=True)


class ParentReportLesson(Base):
    """Локальний рядок розкладу для звітів батькам"""
    __tablename__ = "parent_report_lessons"

    id = Column(Integer, primary_key=True, index=True)
    source_sheet = Column(String, nullable=False, default="Розклад груп")
    source_row = Column(Integer, nullable=False, default=0)
    row_order = Column(Integer, nullable=False, default=0)
    group_name = Column(String, nullable=False, index=True)
    telegram_group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    day = Column(String, nullable=True)
    start_time = Column(String, nullable=True)
    course = Column(String, nullable=True)
    lesson_code = Column(String, nullable=True)
    lesson_count = Column(String, nullable=True)
    lesson_title = Column(Text, nullable=True)
    lesson_topic_detail = Column(Text, nullable=True)
    lesson_report_text = Column(Text, nullable=True)
    topic = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    last_report_date = Column(String, nullable=True)
    absents = Column(Text, nullable=True)
    postponed_start_at = Column(String, nullable=True)
    postponed_from_date = Column(String, nullable=True)
    postponed_created_at = Column(String, nullable=True)
    raw_data = Column(Text, nullable=True)
    imported_at = Column(String, nullable=True)
    telegram_group = relationship("Group")


class ParentReportCourse(Base):
    """Локальний курс для бази звітів батькам"""
    __tablename__ = "parent_report_courses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    source_sheet = Column(String, nullable=True)
    row_order = Column(Integer, nullable=False, default=0)
    raw_data = Column(Text, nullable=True)
    updated_at = Column(String, nullable=True)
    lessons = relationship("ParentReportCourseLesson", back_populates="course", cascade="all, delete-orphan")


class ParentReportCourseLesson(Base):
    """Рядок теми уроку всередині конкретного курсу"""
    __tablename__ = "parent_report_course_lessons"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("parent_report_courses.id"), nullable=False)
    course_name = Column(String, nullable=False, index=True)
    lesson_count = Column(Integer, nullable=False, default=0)
    lesson_code = Column(String, nullable=True)
    module = Column(Text, nullable=True)
    lesson_title = Column(Text, nullable=True)
    lesson_topic_detail = Column(Text, nullable=True)
    lesson_report_text = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    source_sheet = Column(String, nullable=True)
    source_row = Column(Integer, nullable=False, default=0)
    row_order = Column(Integer, nullable=False, default=0)
    raw_data = Column(Text, nullable=True)

    course = relationship("ParentReportCourse", back_populates="lessons")


class ParentReportGroupMap(Base):
    """Зв'язок навчальної групи з Telegram-групою SchoolManager"""
    __tablename__ = "parent_report_group_maps"

    id = Column(Integer, primary_key=True, index=True)
    lesson_group_name = Column(String, nullable=False, unique=True, index=True)
    telegram_group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    updated_at = Column(String, nullable=True)

    telegram_group = relationship("Group")


class ParentReportRun(Base):
    """Журнал сформованих/відправлених звітів"""
    __tablename__ = "parent_report_runs"

    id = Column(Integer, primary_key=True, index=True)
    lesson_group_name = Column(String, nullable=False, index=True)
    lesson_date = Column(String, nullable=False, index=True)
    lesson_id = Column(Integer, nullable=True)
    telegram_group_id = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    absents = Column(Text, nullable=True)
    is_auto = Column(Integer, nullable=False, default=0)
    is_test = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)


class ParentReportNotification(Base):
    """Системні сповіщення про уроки, які потребують звіт"""
    __tablename__ = "parent_report_notifications"

    id = Column(Integer, primary_key=True, index=True)
    lesson_id = Column(Integer, nullable=True, index=True)
    lesson_group_name = Column(String, nullable=False, index=True)
    lesson_date = Column(String, nullable=False, index=True)
    notified_at = Column(String, nullable=False)
