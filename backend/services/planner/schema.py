from sqlalchemy import inspect, text


def ensure_planner_migrations(engine):
    """Add fields introduced during planner previews without touching legacy tables."""
    additions = {
        'planner_items': {'google_connection_id': 'VARCHAR', 'color': 'VARCHAR(7)',
            'location': "TEXT NOT NULL DEFAULT ''", 'recurrence': "TEXT NOT NULL DEFAULT '[]'",
            'attendees': "TEXT NOT NULL DEFAULT '[]'", 'meet_requested': 'INTEGER NOT NULL DEFAULT 0',
            'conference_data': 'TEXT', 'google_calendar_id': 'INTEGER'},
        'planner_connections': {'sync_attempts': 'INTEGER NOT NULL DEFAULT 0', 'events_write': 'INTEGER NOT NULL DEFAULT 0'},
        'planner_calendars': {'sync_window_start': 'VARCHAR', 'sync_format': 'INTEGER NOT NULL DEFAULT 0',
            'access_role': "VARCHAR NOT NULL DEFAULT 'reader'", 'writable': 'INTEGER NOT NULL DEFAULT 0'},
        'planner_external_links': {'pending_snapshot': 'TEXT', 'pending_revision': 'INTEGER'},
        'planner_sync_jobs': {'connection_id': 'VARCHAR'},
    }
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, fields in additions.items():
            if table not in tables:
                continue
            existing = {column['name'] for column in inspector.get_columns(table)}
            for name, sql_type in fields.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}'))
