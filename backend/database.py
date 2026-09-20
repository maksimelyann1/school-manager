# Налаштування бази даних SQLite
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import os
import sys

from app_paths import ensure_runtime_data_dir, migrate_legacy_runtime_data

if getattr(sys, 'frozen', False):
    migrate_legacy_runtime_data()
    db_dir = ensure_runtime_data_dir()
else:
    db_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

db_path = os.path.join(db_dir, "school_manager.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

# Створюємо двигун бази даних
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}  # Для SQLite
)

# Вмикаємо WAL mode для запобігання помилкам "database is locked"
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# Сесія для роботи з БД
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовий клас для моделей
Base = declarative_base()


def get_db():
    """Створює сесію бази даних для кожного запиту"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema_migrations():
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "bot_settings" in table_names:
            bot_settings_columns = {
                column["name"]
                for column in inspector.get_columns("bot_settings")
            }
            if "windows_notifications_enabled" not in bot_settings_columns:
                connection.execute(
                    text("ALTER TABLE bot_settings ADD COLUMN windows_notifications_enabled INTEGER DEFAULT 1")
                )
                connection.execute(
                    text("UPDATE bot_settings SET windows_notifications_enabled = 1 WHERE windows_notifications_enabled IS NULL")
                )

        if "auto_messages" in table_names:
            auto_message_columns = {
                column["name"]
                for column in inspector.get_columns("auto_messages")
            }
            if "stickers" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN stickers TEXT DEFAULT '[]' NOT NULL")
                )
                connection.execute(
                    text("UPDATE auto_messages SET stickers = '[]' WHERE stickers IS NULL")
                )
            if "last_scheduled_for" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN last_scheduled_for VARCHAR")
                )
            if "source" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN source VARCHAR DEFAULT 'manual' NOT NULL")
                )
                connection.execute(
                    text("UPDATE auto_messages SET source = 'manual' WHERE source IS NULL OR source = ''")
                )
            if "parent_report_lesson_id" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN parent_report_lesson_id INTEGER")
                )
            if "parent_report_run_id" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN parent_report_run_id INTEGER")
                )
            if "scheduled_message_id" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN scheduled_message_id INTEGER")
                )
            if "scheduled_target_at" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN scheduled_target_at VARCHAR")
                )
            if "metadata_json" not in auto_message_columns:
                connection.execute(
                    text("ALTER TABLE auto_messages ADD COLUMN metadata_json TEXT")
                )

        if "templates" in table_names:
            template_columns = {
                column["name"]
                for column in inspector.get_columns("templates")
            }
            if "stickers" not in template_columns:
                connection.execute(
                    text("ALTER TABLE templates ADD COLUMN stickers TEXT DEFAULT '[]' NOT NULL")
                )
                connection.execute(
                    text("UPDATE templates SET stickers = '[]' WHERE stickers IS NULL")
                )

        if "parent_report_settings" in table_names:
            parent_settings_columns = {
                column["name"]
                for column in inspector.get_columns("parent_report_settings")
            }
            if "report_notifications_enabled" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN report_notifications_enabled INTEGER DEFAULT 1 NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_settings SET report_notifications_enabled = 1 WHERE report_notifications_enabled IS NULL")
                )
            if "report_notification_delay_minutes" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN report_notification_delay_minutes INTEGER DEFAULT 0 NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_settings SET report_notification_delay_minutes = 0 WHERE report_notification_delay_minutes IS NULL")
                )
            if "absent_followup_enabled" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN absent_followup_enabled INTEGER DEFAULT 1 NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_settings SET absent_followup_enabled = 1 WHERE absent_followup_enabled IS NULL")
                )
            if "absent_followup_schedule_mode" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN absent_followup_schedule_mode VARCHAR DEFAULT 'after_report' NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_settings SET absent_followup_schedule_mode = 'after_report' WHERE absent_followup_schedule_mode IS NULL OR absent_followup_schedule_mode = ''")
                )
            if "absent_followup_delay_minutes" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN absent_followup_delay_minutes INTEGER DEFAULT 5 NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_settings SET absent_followup_delay_minutes = 5 WHERE absent_followup_delay_minutes IS NULL")
                )
            if "absent_followup_before_lesson_time" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN absent_followup_before_lesson_time VARCHAR DEFAULT '20:00' NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_settings SET absent_followup_before_lesson_time = '20:00' WHERE absent_followup_before_lesson_time IS NULL OR absent_followup_before_lesson_time = ''")
                )
            if "absent_followup_template" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN absent_followup_template TEXT")
                )
            if "no_absents_followup_template" not in parent_settings_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_settings ADD COLUMN no_absents_followup_template TEXT")
                )
            if "report_delay_minutes" in parent_settings_columns:
                connection.execute(
                    text(
                        "UPDATE parent_report_settings "
                        "SET report_delay_minutes = 0 "
                        "WHERE report_delay_minutes IS NULL"
                    )
                )

        if "parent_report_lessons" in table_names:
            parent_lesson_columns = {
                column["name"]
                for column in inspector.get_columns("parent_report_lessons")
            }
            if "logika_schedule_id" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN logika_schedule_id INTEGER")
                )
            if "row_order" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN row_order INTEGER DEFAULT 0 NOT NULL")
                )
                connection.execute(
                    text("UPDATE parent_report_lessons SET row_order = source_row WHERE row_order = 0")
                )
            if "telegram_group_id" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN telegram_group_id INTEGER")
                )
            if "lesson_title" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN lesson_title TEXT")
                )
            if "lesson_topic_detail" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN lesson_topic_detail TEXT")
                )
            if "lesson_report_text" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN lesson_report_text TEXT")
                )
            if "postponed_start_at" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN postponed_start_at VARCHAR")
                )
            if "postponed_from_date" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN postponed_from_date VARCHAR")
                )
            if "postponed_created_at" not in parent_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_lessons ADD COLUMN postponed_created_at VARCHAR")
                )
            if {"lesson_report_text", "lesson_topic_detail"}.issubset(parent_lesson_columns | {"lesson_report_text"}):
                clear_columns = []
                if "lesson_report_text" in parent_lesson_columns:
                    clear_columns.append("lesson_report_text = NULL")
                if "lesson_topic_detail" in parent_lesson_columns:
                    clear_columns.append("lesson_topic_detail = NULL")
                if clear_columns:
                    connection.execute(
                        text(f"UPDATE parent_report_lessons SET {', '.join(clear_columns)}")
                    )
            if "parent_report_group_maps" in table_names:
                connection.execute(
                    text(
                        "UPDATE parent_report_lessons "
                        "SET telegram_group_id = ("
                        "SELECT telegram_group_id FROM parent_report_group_maps "
                        "WHERE parent_report_group_maps.lesson_group_name = parent_report_lessons.group_name"
                        ") "
                        "WHERE telegram_group_id IS NULL"
                    )
                )

        if "parent_report_course_lessons" in table_names:
            parent_course_lesson_columns = {
                column["name"]
                for column in inspector.get_columns("parent_report_course_lessons")
            }
            if "lesson_report_text" not in parent_course_lesson_columns:
                connection.execute(
                    text("ALTER TABLE parent_report_course_lessons ADD COLUMN lesson_report_text TEXT")
                )
            connection.execute(text("DELETE FROM parent_report_course_lessons"))
            if {"lesson_count", "source_row"}.issubset(parent_course_lesson_columns):
                connection.execute(
                    text(
                        "UPDATE parent_report_course_lessons "
                        "SET lesson_count = source_row - 1 "
                        "WHERE source_row > 1 AND lesson_count = source_row"
                    )
                )
