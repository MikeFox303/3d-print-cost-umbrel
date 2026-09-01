# 3D Print Cost for umbrelOS

Self-hosted calculator and order ledger for custom 3D-printing services. The project is designed first for **Bambu Lab X2D + AMS 2 Pro** and umbrelOS, while remaining usable with normal Docker Compose.

## Current development version

`0.8.0-dev.1`

### Implemented

- responsive web UI for desktop and phone;
- SQLite persistence plus explicit versioned migrations and pre-migration safety backups;
- local filament price database using actual retail purchase prices;
- **pre-print quote preview** from Bambu Studio time and material grams without saving the order;
- sliced Bambu Studio `.3mf` import for plate time and per-filament `used_g`;
- minimum and recommended customer prices;
- bounded adaptive monthly equipment-payback rate;
- immutable historical pricing/material snapshots;
- order statuses, edit/duplicate, archive, trash/restore and permanent delete;
- business statistics with a 90-day load/payback forecast;
- CSV export, full JSON business-data backup and validated transactional restore;
- Spoolman **read-only** spool price/remaining-weight snapshots;
- Home Assistant **GET-only** post-print energy statistics;
- Home Assistant token configured from the browser and stored separately from SQLite/JSON backups;
- CI regression tests and multi-architecture (`amd64`, `arm64`) container builds;
- Community App package checks for umbrelOS;
- immutable digest pinning for the Umbrel runtime image.

### External-system boundary

- **No Spoolman writes or material deductions.** Bambuddy/Spoolman continue their own inventory workflow independently.
- **Bambuddy is not used for quote calculation.** The quote exists before printing and uses Bambu Studio data.
- Home Assistant is read-only and post-print; its measurement never rewrites the saved quote.

## Quote workflow

1. Slice the model in Bambu Studio.
2. Import the sliced `.3mf` or enter time/material grams manually.
3. Choose a local filament price, use a read-only Spoolman spool snapshot, or enter the actual purchase price manually.
4. Preview minimum/recommended prices without saving.
5. Choose the customer price and save the order.
6. After completion, business statistics record the realized equipment-payback contribution.

## Home Assistant

Normal umbrelOS setup no longer requires an environment variable or SSH. Open **Home Assistant** inside 3D Print Cost and enter the base URL, sensor entity id and Long-Lived Access Token there.

The token is stored as a separate persistent secret file with restrictive permissions. It is not stored in SQLite, is never displayed back in the UI and is excluded from the app's JSON business-data backup. For ordinary Docker deployments, `HOME_ASSISTANT_TOKEN` remains an optional advanced override.

The integration performs only GET requests. It supports cumulative energy sensors (`kWh`/`Wh`) and power-history sensors (`W`/`kW`). The result is post-print statistics only.

## Local Docker run

```bash
docker compose up --build
```

Open `http://localhost:8585`.

Persistent state is stored in the named Docker volume `app-data`. The container runs `python -m app.migrations` before Uvicorn starts.

## umbrelOS package status

The repository contains a Community App Store package:

- `umbrel-app-store.yml`
- `mikefox-3d-print-cost/umbrel-app.yml`
- `mikefox-3d-print-cost/docker-compose.yml`

The `0.8.0-dev.1` runtime image was successfully published for both `amd64` and `arm64` and is pinned in the Umbrel compose to its immutable multi-arch digest:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.8.0-dev.1@sha256:06304d09ffe55b52fa74e58431fd90d29a31e42723a27f8a1e97d76d95353c7f
```

The package is structurally checked in CI, but **real installation on an actual umbrelOS/Raspberry Pi is not claimed yet**. See [`docs/UMBREL_READINESS.md`](docs/UMBREL_READINESS.md) for the remaining device verification checklist.

## Pricing principles

The quote includes actual material cost, electricity estimate, maintenance, minimal manual work, packaging, expected reprint risk, taxes/platform fees, selected margin and a bounded adaptive equipment-payback contribution.

- material reserve is applied once (default 2%);
- expected reprint cost uses `1 / (1 - p)`;
- taxes, percentage platform fees and margin are solved from the **selling price**, not added as simple markups;
- OLX fixed/percentage fees and configured cap are handled explicitly;
- low monthly load cannot increase the payback hourly contribution above the configured cap;
- the adaptive payback rate is snapshotted for the month so customers in the same period are treated consistently.

## Backup / restore

Restore is deliberately replace-all, not merge. It requires a dry-run, exact-file fingerprint and the phrase `RESTORE`; immediately before replacement the app saves a safety copy of the current local business data. External services are never contacted by restore.

## Development

```bash
pip install -r requirements.txt pytest
python -m app.migrations
pytest -q
```

All durable app state belongs under `DATA_DIR`. External services are never treated as writable databases.
