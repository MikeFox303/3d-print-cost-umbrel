# 3D Print Cost for umbrelOS

Self-hosted calculator and order ledger for custom 3D-printing services. The project is designed first for **Bambu Lab X2D + AMS 2 Pro** and umbrelOS, while remaining usable with normal Docker Compose.

## Current development version

`0.11.0-dev.1`

### Implemented

- responsive web UI for desktop and phone, including dedicated real-device scaling for wide, ultrawide and 4K displays;
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
- browser-safe **System Check** for runtime architecture, persistent storage, SQLite, migrations and integration configuration without exposing secrets or making integration network calls;
- CI regression tests and multi-architecture (`amd64`, `arm64`) container builds;
- Community App package checks for umbrelOS;
- anonymous GHCR installability gate plus real amd64/arm64 runtime smoke tests;
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

## System Check

Open **Проверка системы** in the sidebar or `/system`. The page reports:

- application version and container architecture;
- whether persistent `DATA_DIR` exists and is writable;
- SQLite reachability, file presence/size and migration status;
- whether Spoolman/Home Assistant are enabled and configured, without exposing integration URLs or secrets;
- Home Assistant token presence/source without ever returning the token value.

The check itself does not contact Spoolman or Home Assistant. A machine-readable copy is available at `/api/system-check`.

## Real umbrelOS validation

`0.9.0-dev.1` completed the first physical Raspberry Pi/umbrelOS validation: Community App installation, `aarch64` System Check, writable persistent `/data`, SQLite/migrations, app-restart persistence and full host-reboot persistence all passed. `0.10.0-dev.1` was the first real-device interface refresh. `0.11.0-dev.1` is the second pass based directly on ultrawide screenshots, adding dedicated 2400px/3000px scaling and making significantly more of the display usable at normal browser zoom.

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

The package uses a versioned, immutable-digest-pinned GHCR image. Release CI requires the exact pinned image to be anonymously readable because umbrelOS Community App installation does not use GitHub registry credentials.

## Data ownership

All app-owned state is stored under `DATA_DIR`. Updating the container does not replace the persistent database volume. Historical order snapshots remain stable when global settings, filament prices or later application versions change.
