# Architecture

## Runtime

Single FastAPI service + SQLite.

- HTTP: configurable `PORT`, default `8080`
- durable state: `DATA_DIR/3d-cost.db`
- no Redis/Postgres required
- container runs without privileged mode, host network, Docker socket or device access

## External systems

### Spoolman

Read-only optional source. `ReadOnlySpoolmanClient` exposes only `GET /api/v1/spool`. There are deliberately no POST/PATCH/DELETE methods.

The app does not calculate or write inventory depletion. Bambuddy/Spoolman remain authoritative for their own inventory workflow.

### Bambuddy

Not a dependency and not part of quote calculation. Quotes exist before printing, therefore Bambu Studio is the input source for estimated print time and material grams.

### Home Assistant

Planned read-only integration for actual energy after print. It must never be required to quote a job; pre-print pricing uses average power and configured electricity tariff.

## Order data lifecycle

Each saved order snapshots the financial inputs used for the quote. Historical orders are not silently recalculated when global settings or filament prices change.

Delete is soft by default (`deleted_at`), with restore and explicit permanent delete. Archive is independent from trash.
