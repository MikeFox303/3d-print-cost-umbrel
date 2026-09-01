from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.migrations import (
    Migration,
    add_column_if_missing,
    get_applied_versions,
    run_migrations,
)


def file_engine(tmp_path: Path, name: str = "app.db"):
    return create_engine(f"sqlite:///{tmp_path / name}")


def test_fresh_database_is_stamped_at_head(tmp_path):
    engine = file_engine(tmp_path)
    result = run_migrations(engine)

    assert result.head_version == 1
    assert result.applied_now == (1,)
    assert result.safety_backup is None
    assert get_applied_versions(engine) == (1,)
    assert inspect(engine).has_table("orders")
    assert inspect(engine).has_table("schema_migrations")


def test_additive_legacy_migration_preserves_data_and_creates_safety_backup(tmp_path):
    engine = file_engine(tmp_path, "legacy.db")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE legacy_demo (id INTEGER PRIMARY KEY, value TEXT)")
        connection.exec_driver_sql("INSERT INTO legacy_demo (id, value) VALUES (1, 'keep-me')")

    def add_note(connection):
        add_column_if_missing(connection, "legacy_demo", "note", "TEXT DEFAULT ''")

    migrations = (
        Migration(1, "baseline", lambda connection: None, requires_backup=False),
        Migration(2, "legacy-demo-note", add_note, requires_backup=True),
    )
    safety_dir = tmp_path / "safety"
    result = run_migrations(engine, migrations=migrations, safety_dir=safety_dir)

    assert result.applied_now == (1, 2)
    assert result.safety_backup is not None
    assert (safety_dir / result.safety_backup).exists()
    assert get_applied_versions(engine) == (1, 2)
    assert "note" in {column["name"] for column in inspect(engine).get_columns("legacy_demo")}
    with engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT id, value, note FROM legacy_demo").one()
    assert tuple(row) == (1, "keep-me", "")

    # Idempotent second boot: no DDL and no extra safety backup.
    second = run_migrations(engine, migrations=migrations, safety_dir=safety_dir)
    assert second.applied_now == ()
    assert second.safety_backup is None


def test_failed_migration_is_not_marked_applied(tmp_path):
    engine = file_engine(tmp_path, "failure.db")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE legacy_demo (id INTEGER PRIMARY KEY, value TEXT)")
        connection.exec_driver_sql("INSERT INTO legacy_demo (id, value) VALUES (1, 'original')")

    def fail(connection):
        connection.exec_driver_sql("UPDATE legacy_demo SET value='changed' WHERE id=1")
        raise RuntimeError("boom")

    migrations = (
        Migration(1, "baseline", lambda connection: None, requires_backup=False),
        Migration(2, "failing", fail, requires_backup=True),
    )
    with pytest.raises(RuntimeError, match="boom"):
        run_migrations(engine, migrations=migrations, safety_dir=tmp_path / "safety")

    # The migration transaction rolls back both the data change and the marker.
    assert get_applied_versions(engine) == ()
    with engine.connect() as connection:
        value = connection.exec_driver_sql("SELECT value FROM legacy_demo WHERE id=1").scalar_one()
    assert value == "original"


def test_newer_database_is_rejected(tmp_path):
    engine = file_engine(tmp_path, "newer.db")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO schema_migrations VALUES (99, 'future', '2026-09-01T00:00:00+00:00')"
        )

    with pytest.raises(RuntimeError, match="newer than this application"):
        run_migrations(engine)
