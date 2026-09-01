# Architecture

## Runtime

Single FastAPI service + SQLite.

- HTTP: configurable `PORT`, default `8080`
- durable state: `DATA_DIR/3d-cost.db`
- no Redis/Postgres required
- container runs without privileged mode, host network, Docker socket or device access
- UI and API are served by the same container

## Pre-print quote path

The app must be able to calculate a quote **before the printer starts**.

```text
Bambu Studio (slice)
        |
        | estimated time + total material grams
        v
3D Print Cost
        |
        +-- local filament purchase-price database
        +-- optional Spoolman GET-only snapshot
        +-- pricing/settings snapshot
        v
minimum + recommended quote
```

Bambuddy is not part of this path.

## External systems

### Spoolman

Optional, read-only source. `ReadOnlySpoolmanClient` exposes only GET behavior. There are deliberately no POST/PATCH/PUT/DELETE methods.

A Spoolman spool can be inserted into a quote as a snapshot containing:

- spool ID;
- vendor/name/material;
- current `remaining_weight`;
- effective purchase price;
- price per gram.

Spoolman's own price semantics are respected: a spool-specific `spool.price` overrides `filament.price`; if no spool price exists the filament price is used. The denominator is `initial_weight` when available, otherwise the filament's nominal full-spool `weight`.

The app does **not** calculate or write inventory depletion. Bambuddy/Spoolman remain authoritative for their own inventory workflow.

### Bambuddy

Not a dependency and not part of quote calculation. The app neither reads nor writes Bambuddy in the current architecture.

### Home Assistant

Planned GET-only integration for actual energy after print. It must never be required to quote a job; pre-print pricing uses average power and configured electricity tariff unless explicit kWh are supplied manually.

## Order data lifecycle

Each saved order snapshots the financial inputs used for the quote. Historical orders are not silently recalculated when global settings or filament prices change.

- non-completed orders can be edited and recalculated;
- completed orders are financially immutable and should be duplicated if a similar new order is needed;
- duplicate opens a new draft using the previous order as a starting point;
- delete is soft by default (`deleted_at`), with restore and explicit permanent delete;
- archive is independent from trash.

## Quote preview

`POST /api/quotes/preview` calculates the full price breakdown from form data but does not create an order. The same server-side pricing functions are used when the order is finally saved, so preview and persisted calculations share one source of truth.
