# 3D Print Cost for umbrelOS

Self-hosted calculator and order ledger for 3D-printing services. The project is designed first for **Bambu Lab X2D + AMS 2 Pro** and umbrelOS, while remaining usable with normal Docker Compose.

## Current development version

`0.1.0-dev.1`

### Implemented

- responsive web UI for desktop and phone;
- SQLite persistence in a configurable data directory;
- local filament price database using actual retail purchase prices;
- pre-print calculation from Bambu Studio time and material grams;
- minimum price and recommended price;
- adaptive monthly payback rate with a floor reference load and min/max rate caps;
- order snapshots so later price/settings changes do not rewrite history;
- order statuses, archive, soft-delete/trash, restore and permanent delete;
- realized payback recorded when an order is completed;
- Spoolman **read-only** client (`GET` only) for viewing current spool data;
- umbrelOS community-app package skeleton;
- multi-architecture GHCR build workflow for `amd64` and `arm64`.

### Deliberately not implemented

- No Spoolman writes or material deductions. Spoolman/Bambuddy continue to manage inventory independently.
- No Bambuddy integration for quote calculation. Quotes are calculated **before printing** from Bambu Studio data.
- Home Assistant energy history import is planned; until then the quote uses configured average power or manually entered kWh.
- 3MF import is planned.

## Local Docker run

```bash
docker compose up --build
```

Open `http://localhost:8585`.

Persistent state is stored in the named Docker volume `app-data`.

## Umbrel packaging

This repository is also structured as a small Community App Store:

- `umbrel-app-store.yml`
- `mikefox-3d-print-cost/umbrel-app.yml`
- `mikefox-3d-print-cost/docker-compose.yml`

The Umbrel package uses the GHCR image produced by the GitHub Actions workflow. The web UI is protected by Umbrel `app_proxy` authentication.

## Pricing principles

The customer quote is calculated before print from:

1. actual material cost (grams × stored price per gram);
2. electricity estimate or explicit kWh;
3. maintenance reserve;
4. minimal manual-labor allowance;
5. packaging;
6. complexity/risk reserve;
7. tax and platform fees;
8. selected margin;
9. a bounded adaptive payback contribution.

The payback rate is deliberately capped so a low number of monthly orders does not force a random customer to finance printer idle time. The monthly rate is snapshotted and completed-order income affects the amount actually credited toward equipment recovery.

## Data ownership

All app-owned state is stored in SQLite under `DATA_DIR`. External services are not treated as writable databases.
