import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.infrastructure.database import (
    apply_migrations,
    connect_database,
    migrate_database,
    resolve_database_path,
)


class DatabaseConnectionTests(unittest.TestCase):
    def test_connection_creates_parent_directory_and_enables_foreign_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "ai-trader.sqlite3"
            connection = connect_database(path)
            try:
                self.assertTrue(path.parent.exists())
                self.assertIsInstance(connection, sqlite3.Connection)
                self.assertIsNotNone(connection.execute("PRAGMA foreign_keys").fetchone())
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
                )
                self.assertIsInstance(
                    connection.execute("SELECT 1 AS value").fetchone(),
                    sqlite3.Row,
                )
            finally:
                connection.close()

    def test_memory_database_does_not_create_a_filesystem_path(self):
        connection = connect_database(":memory:")
        try:
            self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)
        finally:
            connection.close()

    def test_environment_path_is_used_when_no_explicit_path_is_given(self):
        with patch.dict("os.environ", {"AI_TRADER_DB_PATH": "~/custom/trader.sqlite3"}):
            self.assertEqual(
                resolve_database_path(),
                Path("~/custom/trader.sqlite3").expanduser(),
            )

    def test_explicit_path_takes_precedence_over_environment(self):
        with patch.dict("os.environ", {"AI_TRADER_DB_PATH": "/tmp/from-env.sqlite3"}):
            self.assertEqual(
                resolve_database_path("/tmp/explicit.sqlite3"),
                Path("/tmp/explicit.sqlite3"),
            )


class DatabaseMigrationTests(unittest.TestCase):
    def write_migration(self, directory, filename, content):
        path = Path(directory) / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_migrations_apply_in_order_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            migration_dir = Path(temporary) / "migrations"
            migration_dir.mkdir()
            self.write_migration(
                migration_dir,
                "0002_add_status.sql",
                "ALTER TABLE accounts ADD COLUMN status TEXT NOT NULL DEFAULT 'active';",
            )
            self.write_migration(
                migration_dir,
                "0001_create_accounts.sql",
                "CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT NOT NULL);",
            )

            connection = connect_database(":memory:")
            try:
                self.assertEqual(
                    apply_migrations(connection, migration_dir), ["0001", "0002"]
                )
                self.assertEqual(apply_migrations(connection, migration_dir), [])
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(accounts)")
                }
                self.assertEqual(columns, {"id", "name", "status"})
                versions = [
                    row["version"]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                self.assertEqual(versions, ["0001", "0002"])
            finally:
                connection.close()

    def test_failed_migration_rolls_back_schema_and_version_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            migration_dir = Path(temporary) / "migrations"
            migration_dir.mkdir()
            self.write_migration(
                migration_dir,
                "0001_broken_migration.sql",
                "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\n"
                "THIS IS NOT VALID SQL;",
            )

            connection = connect_database(":memory:")
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    apply_migrations(connection, migration_dir)
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertNotIn("should_rollback", tables)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM schema_migrations"
                    ).fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_immutable_audit_migration_preserves_existing_events_and_is_idempotent(self):
        repository_root = Path(__file__).resolve().parents[1]
        migrations_dir = repository_root / "backend" / "infrastructure" / "migrations"

        with tempfile.TemporaryDirectory() as temporary:
            legacy_dir = Path(temporary) / "legacy_migrations"
            legacy_dir.mkdir()
            for version in range(1, 5):
                source = next(migrations_dir.glob(f"{version:04d}_*.sql"))
                shutil.copyfile(source, legacy_dir / source.name)

            connection = connect_database(":memory:")
            try:
                self.assertEqual(
                    apply_migrations(connection, legacy_dir),
                    ["0001", "0002", "0003", "0004"],
                )
                # Include a real trade reference so foreign_key_check validates
                # the rebuilt audit table's relationship, not only NULL references.
                connection.execute(
                    """
                    INSERT INTO paper_trades
                        (id, symbol, strategy, side, quantity, entry_price,
                         entry_fee, status, opened_at, metadata_json)
                    VALUES (?, 'SOLUSDT', 'migration-test', 'LONG', '1',
                            '100', '0', 'OPEN', ?, '{}')
                    """,
                    ("legacy-trade-1", "2026-11-11T09:00:00Z"),
                )
                connection.executemany(
                    """
                    INSERT INTO paper_trade_events
                        (id, trade_id, event_type, details_json, occurred_at)
                    VALUES (?, NULL, 'CIRCUIT_BREAKER_HALTED', ?, ?)
                    """,
                    [
                        ("legacy-event-1", '{"reason":"first"}', "2026-11-11T10:00:00Z"),
                        ("legacy-event-2", '{"reason":"second"}', "2026-11-11T10:00:00Z"),
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO paper_trade_events
                        (id, trade_id, event_type, details_json, occurred_at)
                    VALUES (?, ?, 'TRADE_OPENED', '{}', ?)
                    """,
                    (
                        "legacy-trade-event",
                        "legacy-trade-1",
                        "2026-11-11T09:00:00Z",
                    ),
                )
                connection.commit()

                self.assertEqual(apply_migrations(connection, migrations_dir), ["0005", "0006"])
                legacy_trade = connection.execute(
                    "SELECT paper_account_id FROM paper_trades WHERE id = 'legacy-trade-1'"
                ).fetchone()
                self.assertIsNone(legacy_trade["paper_account_id"])
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM paper_accounts").fetchone()[0],
                    0,
                )
                rows = connection.execute(
                    """
                    SELECT sequence, id, trade_id, details_json
                    FROM paper_trade_events
                    ORDER BY sequence
                    """
                ).fetchall()
                self.assertEqual(
                    [(row["id"], row["details_json"]) for row in rows],
                    [
                        ("legacy-event-1", '{"reason":"first"}'),
                        ("legacy-event-2", '{"reason":"second"}'),
                        ("legacy-trade-event", "{}"),
                    ],
                )
                self.assertEqual([row["sequence"] for row in rows], [1, 2, 3])
                self.assertEqual(rows[2]["trade_id"], "legacy-trade-1")
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(), []
                )
                self.assertEqual(apply_migrations(connection, migrations_dir), [])
            finally:
                connection.close()

    def test_invalid_migration_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            migration_dir = Path(temporary) / "migrations"
            migration_dir.mkdir()
            self.write_migration(migration_dir, "initial.sql", "CREATE TABLE x (id);")
            connection = connect_database(":memory:")
            try:
                with self.assertRaisesRegex(ValueError, "Nombre de migración inválido"):
                    apply_migrations(connection, migration_dir)
            finally:
                connection.close()

    def test_migrate_database_closes_database_after_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            migration_dir = Path(temporary) / "migrations"
            migration_dir.mkdir()
            self.write_migration(
                migration_dir,
                "0001_create_settings.sql",
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);",
            )
            database_path = Path(temporary) / "db" / "app.sqlite3"
            self.assertEqual(
                migrate_database(database_path, migration_dir), ["0001"]
            )
            self.assertTrue(database_path.exists())


if __name__ == "__main__":
    unittest.main()
