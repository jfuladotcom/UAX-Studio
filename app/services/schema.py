from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from flask_migrate import stamp, upgrade
from sqlalchemy import inspect, text

from app.extensions import db

LEGACY_BASELINE = "0000_legacy_baseline"
SCHEMA_HEAD = "0001_inclusion_status"


def ensure_database_schema() -> Path | None:
    """Upgrade the local database, backing up existing SQLite data first."""
    migrations_dir = Path(current_app.root_path) / "migrations"
    tables = set(inspect(db.engine).get_table_names())
    application_tables = tables - {"alembic_version"}
    current_revision = _current_revision(tables)

    if current_revision == SCHEMA_HEAD:
        return None

    backup = _backup_sqlite_database() if application_tables else None
    if application_tables and not current_revision:
        stamp(directory=str(migrations_dir), revision=LEGACY_BASELINE)
    upgrade(directory=str(migrations_dir), revision="head")
    return backup


def _current_revision(tables: set[str]) -> str | None:
    if "alembic_version" not in tables:
        return None
    with db.engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _backup_sqlite_database() -> Path | None:
    database_path = db.engine.url.database
    if db.engine.dialect.name != "sqlite" or not database_path or database_path == ":memory:":
        return None

    source_path = Path(database_path).resolve()
    if not source_path.exists() or not source_path.stat().st_size:
        return None

    backup_dir = source_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{source_path.stem}-{timestamp}{source_path.suffix}"
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path
