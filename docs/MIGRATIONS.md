# Database migrations

Starting with `0.7.0-dev.1`, the container runs `python -m app.migrations` before the web server starts.

## Goals

- Preserve existing SQLite orders and financial snapshots across schema changes.
- Keep migrations ordered, explicit and testable.
- Refuse to start an older application build against a database that declares a newer migration version.
- Automatically create a SQLite safety copy before a pending migration marked `requires_backup=True` changes an existing database.

## Tracking table

The app owns a small `schema_migrations` table:

```text
version | name | applied_at
```

Version `1` is the baseline representing the schema that already existed through `0.6.x`.

## Adding a migration

Append a `Migration(...)` entry to `MIGRATIONS` in `app/migrations.py`. Versions are positive, unique integers and execute in ascending order.

For additive SQLite changes use `add_column_if_missing()` where possible. Migration functions must be deterministic and idempotent enough to be safely inspected/tested.

Example:

```python
def add_notes(connection):
    add_column_if_missing(connection, "orders", "notes", "TEXT DEFAULT ''")

MIGRATIONS = (
    ...,
    Migration(2, "orders-notes", add_notes, requires_backup=True),
)
```

For a fresh database, missing legacy tables are skipped by additive helpers and `Base.metadata.create_all()` creates the current head schema after the migration markers are recorded.

## Safety backups

For a file-backed SQLite database with an existing application schema, any pending migration with `requires_backup=True` creates a consistent copy through SQLite's backup API under:

```text
DATA_DIR/migration-safety/
```

The copy is created before the migration transaction. Baseline stamping alone does not create a redundant backup.

## JSON restore

JSON backup/restore does not export or overwrite `schema_migrations`. The migration version describes the local database schema, not user-owned business data. Restored user data is loaded into the schema of the running application build.
