# 3D Print Cost for umbrelOS

Self-hosted calculator and order ledger for custom 3D-printing services. The project is designed first for **Bambu Lab X2D + AMS 2 Pro** and umbrelOS, while remaining usable with normal Docker Compose.

## Current development version

`0.2.0-dev.1`

### Implemented

- responsive web UI for desktop and phone;
- SQLite persistence in a configurable data directory;
- local filament price database using actual retail purchase prices;
- **pre-print quote preview** from Bambu Studio time and material grams without saving the order;
- minimum price and recommended price;
- bounded adaptive monthly payback rate with a reference-load floor and min/max rate caps;
- order snapshots so later price/settings changes do not rewrite history;
- order statuses, edit for non-completed orders, duplicate, archive, soft-delete/trash, restore and permanent delete;
- completed orders are protected from financial editing — duplicate them instead;
- realized payback recorded when an order is completed;
- Spoolman **read-only** client (`GET` only) for viewing current spool data;
- read-only Spoolman spool can be inserted into a quote as a snapshot of price/remaining weight;
- warning when quoted grams exceed the Spoolman remaining weight snapshot;
- umbrelOS Community App package skeleton;
- CI tests on pull requests;
- multi-architecture GHCR image build for `amd64` and `arm64` after tests pass.

### Deliberately not implemented

- **No Spoolman writes or material deductions.** Spoolman/Bambuddy continue to manage inventory independently.
- **No Bambuddy integration for quote calculation.** Quotes are calculated before printing from Bambu Studio data.
- Home Assistant energy history import is planned; until then a quote uses configured average power or manually entered kWh.
- `.3mf` import is planned.

## Local Docker run

```bash
docker compose up --build
```

Open `http://localhost:8585`.

Persistent state is stored in the named Docker volume `app-data`.

## umbrelOS packaging

This repository is also structured as a small Community App Store:

- `umbrel-app-store.yml`
- `mikefox-3d-print-cost/umbrel-app.yml`
- `mikefox-3d-print-cost/docker-compose.yml`

The Umbrel package uses the GHCR image produced by GitHub Actions. The web UI is protected by Umbrel `app_proxy` authentication.

## Quote workflow

1. Slice the model in Bambu Studio.
2. Enter estimated print time and total grams for each material, or select a local saved filament price.
3. Optionally read a current Spoolman spool and insert its price/remaining-weight snapshot into the quote.
4. Press **Calculate price**. Nothing is saved yet.
5. Review minimum/recommended prices and the cost breakdown.
6. Set the customer price and save the order.
7. After completion, the final customer price determines how much payback contribution was actually realized.

## Pricing principles

The customer quote is calculated before print from:

1. actual material cost (grams × snapshotted price per gram);
2. electricity estimate or explicit kWh;
3. maintenance reserve;
4. minimal manual-labor allowance;
5. packaging;
6. complexity/risk reserve;
7. tax and platform fees;
8. selected margin;
9. a bounded adaptive payback contribution.

The payback rate is deliberately capped so a low number of monthly orders does not force a random customer to finance printer idle time. The monthly rate is snapshotted, and completed-order income affects the amount actually credited toward equipment recovery.

## External systems

### Spoolman

Read only. The client contains no methods for updating inventory. Spoolman/Bambuddy remain responsible for their own material deductions.

Spoolman supports both a spool-specific price and a filament default price. The app follows Spoolman's own precedence: spool price first, then filament price. For cost per gram it uses the spool's initial net filament weight when available, otherwise the nominal filament weight.

### Bambuddy

Not used by this app. It can continue working with Spoolman independently.

### Home Assistant

Planned as a GET-only source of actual energy statistics after a print. It will never be required for a pre-print quote.

## Development

```bash
pip install -r requirements.txt pytest
pytest -q
```

All durable app state belongs to SQLite under `DATA_DIR`. External services are never treated as writable databases.
