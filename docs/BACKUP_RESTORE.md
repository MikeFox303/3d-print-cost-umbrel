# JSON backup restore safety model

The restore feature accepts only the application's own `3d-print-cost-backup-v1` JSON structure.

## Two-stage flow

1. **Preview / dry-run** reads and validates the complete file without changing the database.
2. Preview returns a SHA-256 fingerprint and a confirmation token bound to those exact bytes.
3. **Apply** requires the same file, that token, and the literal confirmation phrase `RESTORE`.

Changing even one byte in the file invalidates the preview token.

## Validation

Before apply, the restore engine checks:

- schema identifier and maximum upload size (25 MiB);
- known settings and their JSON types;
- filament and order IDs for uniqueness;
- material-to-filament references;
- order status, complexity and platform enums;
- finite numeric values and basic non-negative/range constraints;
- ISO timestamps;
- monthly payback keys (`YYYY-MM`) and uniqueness.

Unknown future settings are not written. Missing current settings are replaced with the current application defaults and reported in the preview.

## Apply semantics

Restore is intentionally **replace-all**, not merge. The backup contains historical IDs and snapshot references, so replace-all has deterministic semantics and avoids collisions with a partially populated current database.

Immediately before replacement, the app writes the complete current local state to:

`DATA_DIR/restore-safety/before-restore-<timestamp>.json`

The actual replacement of settings, local filaments, orders, order-material snapshots and monthly payback rates runs inside one SQLAlchemy transaction. Any database error rolls that transaction back.

## External systems

Restore has no code path to the printer, Bambu Cloud, Bambuddy, Spoolman or Home Assistant. External inventory and device state are never restored or mutated.
