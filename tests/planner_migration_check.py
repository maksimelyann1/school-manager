"""Verify additive planner schema on a private backup of the existing database."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import create_engine
from database import Base
import models
import task_models
from services.planner.schema import ensure_planner_migrations


def fingerprint(connection):
    result = {}
    tables = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'planner_%' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    for name, schema in tables:
        checksum = hashlib.sha256(schema.encode())
        rows = connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall()
        for row in sorted(map(repr, rows)):
            checksum.update(row.encode('utf-8'))
        result[name] = (len(rows), checksum.hexdigest())
    return result


if __name__ == '__main__':
    source = ROOT / 'school_manager.db'
    with tempfile.TemporaryDirectory(prefix='planner-schema-check-') as temporary:
        copy = Path(temporary) / 'copy.db'
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(copy)) as backup:
            original.backup(backup)
            before = fingerprint(backup)
        engine = create_engine(f'sqlite:///{copy}')
        planner_tables = [table for name, table in Base.metadata.tables.items() if name.startswith('planner_')]
        Base.metadata.create_all(engine, tables=planner_tables)
        ensure_planner_migrations(engine)
        Base.metadata.create_all(engine, tables=planner_tables)
        ensure_planner_migrations(engine)
        engine.dispose()
        with closing(sqlite3.connect(copy)) as backup:
            after = fingerprint(backup)
            added = backup.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'planner_%'").fetchone()[0]
        result = {'ok': before == after, 'existing_tables_unchanged': len(before), 'planner_tables': added, 'idempotent': True}
        Path(ROOT / 'output/playwright/migration-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        raise SystemExit(0 if result['ok'] else 1)
