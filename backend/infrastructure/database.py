"""SQLite connection and versioned SQL migration infrastructure.

The module has no import-time filesystem or database side effects. Callers
choose when to open a connection and when to apply migrations.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Iterator


_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")


def resolve_database_path(path: str | Path | None = None) -> Path:
    """Resolve an explicit path, environment override, or local default."""
    if path is not None:
        return Path(path).expanduser()

    configured = os.environ.get("AI_TRADER_DB_PATH")
    if configured:
        return Path(configured).expanduser()

    repository_root = Path(__file__).resolve().parents[2]
    return repository_root / "data" / "ai_trader.sqlite3"


def connect_database(path: str | Path | None = None) -> sqlite3.Connection:
    """Open SQLite with consistent row, foreign-key and busy-timeout settings."""
    resolved = resolve_database_path(path)
    is_memory = str(resolved) == ":memory:"
    if not is_memory:
        resolved.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(resolved), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _iter_sql_statements(script: str) -> Iterator[str]:
    """Split a migration script at complete SQLite statements."""
    pending = ""
    for character in script:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ""

    if pending.strip():
        if not sqlite3.complete_statement(pending):
            raise ValueError("La migración contiene una sentencia SQL incompleta")
        yield pending.strip()


def _migration_files(migrations_dir: str | Path) -> list[tuple[str, Path]]:
    directory = Path(migrations_dir)
    if not directory.exists():
        return []

    migrations = []
    seen_versions = set()
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if not match:
            raise ValueError(
                f"Nombre de migración inválido: {path.name}; "
                "usa NNNN_descripcion.sql"
            )
        version = match.group("version")
        if version in seen_versions:
            raise ValueError(f"Versión de migración duplicada: {version}")
        seen_versions.add(version)
        migrations.append((version, path))
    return migrations


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path | None = None,
) -> list[str]:
    """Apply pending migrations once, each inside its own transaction."""
    if connection.in_transaction:
        raise RuntimeError("La conexión ya tiene una transacción activa")

    if migrations_dir is None:
        migrations_dir = Path(__file__).with_name("migrations")

    migrations = _migration_files(migrations_dir)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()

    applied_now = []
    for version, migration_path in migrations:
        script = migration_path.read_text(encoding="utf-8")
        statements = list(_iter_sql_statements(script))
        if not statements:
            raise ValueError(f"La migración está vacía: {migration_path.name}")

        connection.execute("BEGIN IMMEDIATE")
        try:
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if already_applied:
                connection.commit()
                continue

            for statement in statements:
                connection.execute(statement)

            connection.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, migration_path.name),
            )
            connection.commit()
            applied_now.append(version)
        except Exception:
            connection.rollback()
            raise

    return applied_now


def migrate_database(
    path: str | Path | None = None,
    migrations_dir: str | Path | None = None,
) -> list[str]:
    """Open, migrate and close a database, returning versions applied now."""
    connection = connect_database(path)
    try:
        return apply_migrations(connection, migrations_dir)
    finally:
        connection.close()
