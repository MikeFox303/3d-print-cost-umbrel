from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import Engine, inspect
from sqlalchemy.engine import Connection

from .db import Base, DATA_DIR, engine

MIGRATION_TABLE = "schema_migrations"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]
    requires_backup: bool = True


@dataclass(frozen=True)
class MigrationResult:
    head_version: int
    previously_applied: tuple[int, ...]
    applied_now: tuple[int, ...]
    safety_backup: str | None

    def to_dict(self) -> dict:
        return {
            "head_version": self.head_version,
            "previously_applied": list(self.previously_applied),
            "applied_now": list(self.applied_now),
            "safety_backup": self.safety_backup,
        }


def _baseline(_connection: Connection) -> None:
    """v1 is the schema shipped before explicit migration tracking existed."""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline-v0.6-schema", _baseline, requires_backup=False),
)


def _validated_migrations(migrations: Iterable[Migration]) -> tuple[Migration, ...]:
    items = tuple(sorted(migrations, key=lambda item: item.version))
    if not items:
        raise ValueError("Migration list must not be empty")
    versions = [item.version for item in items]
    if any(version <= 0 for version in versions):
        raise ValueError("Migration versions must be positive integers")
    if len(versions) != len(set(versions)):
        raise ValueError("Migration versions must be unique")
    return items


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def table_exists(connection: Connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def column_exists(connection: Connection, table_name: str, column_name: str) -> bool:
    if not table_exists(connection, table_name):
        return False
    return any(column["name"] == column_name for column in inspect(connection).get_columns(table_name))


def add_column_if_missing(
    connection: Connection,
    table_name: str,
    column_name: str,
    column_ddl: str,
) -> bool:
    """SQLite-safe helper for future additive migrations.

    `column_ddl` is static developer-authored SQL, for example `TEXT DEFAULT ''`.
    Table/column identifiers are separately validated and quoted.
    """
    if not table_exists(connection, table_name):
        return False
    if column_exists(connection, table_name, column_name):
        return False
    table = _quote_identifier(table_name)
    column = _quote_identifier(column_name)
    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")
    return True


def _migration_table_exists(db_engine: Engine) -> bool:
    return inspect(db_engine).has_table(MIGRATION_TABLE)


def _existing_non_migration_tables(db_engine: Engine) -> set[str]:
    return set(inspect(db_engine).get_table_names()) - {MIGRATION_TABLE}


def get_applied_versions(db_engine: Engine) -> tuple[int, ...]:
    if not _migration_table_exists(db_engine):
        return ()
    with db_engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT version FROM {MIGRATION_TABLE} ORDER BY version"
        ).all()
    return tuple(int(row[0]) for row in rows)


def _ensure_migration_table(connection: Connection) -> None:
    connection.exec_driver_sql(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _sqlite_database_path(db_engine: Engine) -> Path | None:
    if db_engine.dialect.name != "sqlite":
        return None
    database = db_engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser().resolve()


def create_migration_safety_backup(
    db_engine: Engine,
    *,
    safety_dir: Path | None = None,
    target_version: int,
) -> Path | None:
    source_path = _sqlite_database_path(db_engine)
    if source_path is None or not source_path.exists():
        return None

    directory = safety_dir or (DATA_DIR / "migration-safety")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination = directory / f"before-schema-v{target_version}-{stamp}.db"

    source = sqlite3.connect(str(source_path))
    destination_db = sqlite3.connect(str(destination))
    try:
        source.backup(destination_db)
    finally:
        destination_db.close()
        source.close()
    return destination


def run_migrations(
    db_engine: Engine,
    *,
    migrations: Iterable[Migration] = MIGRATIONS,
    safety_dir: Path | None = None,
) -> MigrationResult:
    items = _validated_migrations(migrations)
    head = items[-1].version
    previously_applied = get_applied_versions(db_engine)
    applied_set = set(previously_applied)
    pending = [migration for migration in items if migration.version not in applied_set]

    known_versions = {migration.version for migration in items}
    unknown_applied = sorted(applied_set - known_versions)
    if unknown_applied:
        raise RuntimeError(
            "Database schema is newer than this application build: "
            + ", ".join(map(str, unknown_applied))
        )

    existing_tables = _existing_non_migration_tables(db_engine)
    safety_path: Path | None = None
    if existing_tables and any(migration.requires_backup for migration in pending):
        safety_path = create_migration_safety_backup(
            db_engine,
            safety_dir=safety_dir,
            target_version=head,
        )

    applied_now: list[int] = []
    with db_engine.begin() as connection:
        _ensure_migration_table(connection)
        for migration in pending:
            migration.apply(connection)
            connection.exec_driver_sql(
                f"INSERT INTO {MIGRATION_TABLE} (version, name, applied_at) VALUES (?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            applied_now.append(migration.version)

    # create_all is intentionally after migrations. On a legacy database, migrations
    # transform existing tables first; on a fresh database it creates the current head.
    Base.metadata.create_all(bind=db_engine)

    return MigrationResult(
        head_version=head,
        previously_applied=previously_applied,
        applied_now=tuple(applied_now),
        safety_backup=safety_path.name if safety_path else None,
    )


def migration_status(db_engine: Engine, migrations: Iterable[Migration] = MIGRATIONS) -> dict:
    items = _validated_migrations(migrations)
    applied = get_applied_versions(db_engine)
    return {
        "head_version": items[-1].version,
        "applied_versions": list(applied),
        "up_to_date": bool(applied) and applied[-1] == items[-1].version,
    }


def main() -> None:
    result = run_migrations(engine)
    print(
        f"Schema head v{result.head_version}; "
        f"applied now: {list(result.applied_now) or 'none'}; "
        f"safety backup: {result.safety_backup or 'not needed'}"
    )


if __name__ == "__main__":
    main()
