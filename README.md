# 3D Print Cost for umbrelOS

Self-hosted calculator and order ledger for custom 3D-printing services. The project is designed first for **Bambu Lab X2D + AMS 2 Pro** and umbrelOS, while remaining usable with normal Docker Compose.

## Current development version

`0.14.0-dev.1`

The currently released Community App package remains `0.13.0-dev.1`, pinned to an immutable multi-architecture GHCR digest while v0.14 source changes are tested separately.

### Implemented

- responsive web UI for desktop and phone, including dedicated real-device scaling for wide, ultrawide, 4K displays and a phone-first real-device pass;
- safe iPhone/Home Screen standalone shell in v0.14 with a web app manifest, touch icons and standalone safe-area styling;
- SQLite persistence plus explicit versioned migrations and pre-migration safety backups;
- local filament price database using actual retail purchase prices;
- **pre-print quote preview** from Bambu Studio time and material grams without saving the order;
- sliced Bambu Studio `.3mf` import for plate time and per-filament `used_g`;
- conservative `.3mf` → local filament-price matching: unique material matches can be selected automatically, ambiguous matches remain manual;
- minimum and recommended customer prices;
- bounded adaptive monthly equipment-payback rate;
- immutable historical pricing/material snapshots;
- economics evaluated at the **actual customer price**, including actual-price profit and realized equipment-payback contribution;
- client-safe copyable quote text that never exposes internal cost, margin, tax or payback details;
- order statuses, edit/duplicate, archive, trash/restore and permanent delete;
- business statistics with a 90-day load/payback forecast;
- snapshot-only **price-discipline analytics** for completed v0.13+ orders, with legacy orders kept separate;
- CSV export, full JSON business-data backup and validated transactional restore;
- Spoolman **read-only** spool price/remaining-weight snapshots;
- Home Assistant **GET-only** post-print electricity reconciliation using the tariff/kWh basis saved with the quote;
- Home Assistant token configured from the browser and stored separately from SQLite/JSON backups;
- browser-safe **System Check** for runtime architecture, persistent storage, SQLite, migrations and integration configuration without exposing secrets or making integration network calls;
- CI regression tests and multi-architecture (`amd64`, `arm64`) container builds;
- Community App package checks for umbrelOS;
- anonymous GHCR installability gate plus real amd64/arm64 runtime smoke tests;
- immutable digest pinning for the Umbrel runtime image.

### External-system boundary

- **No Spoolman writes or material deductions.** Bambuddy/Spoolman continue their own inventory workflow independently.
- **Bambuddy is not used for quote calculation.** The quote exists before printing and uses Bambu Studio data.
- Home Assistant is read-only and post-print; its measurement never rewrites the saved quote, customer price or realized payback.

## Quote workflow

1. Slice the model in Bambu Studio.
2. Import the sliced `.3mf` or enter time/material grams manually.
3. For imported material rows, use an unambiguous local price match when available; otherwise choose the real local filament, use a read-only Spoolman spool snapshot, or enter the actual purchase price manually.
4. Preview minimum/recommended prices without saving.
5. Choose the customer price and review the economics at that exact price.
6. Copy the client-safe quote text if needed and save the order.
7. After completion, business statistics record the realized equipment-payback contribution.
8. Optionally compare quote-time electricity with read-only Home Assistant measurements; this is statistics only and never retroactively reprices the order.

The `.3mf` matcher deliberately does not guess across different material families. It only ignores punctuation, spacing and case (`PETG-HF` can match `PETG HF`), while labels such as `PLA-S` remain distinct from generic `PLA`. If several same-material local spools exist and color does not uniquely disambiguate them, the user must choose the real spool.

## iPhone / standalone web app

v0.14 adds a web app manifest and iOS standalone metadata so the local interface can be added to the iPhone Home Screen and opened without normal Safari chrome.

This is intentionally **not an offline business application**. There is no service worker and no offline fallback for orders, quotes, settings, Spoolman or Home Assistant data. Umbrel/SQLite remains the single authoritative source, preventing a stale cached quote or order form from looking editable while disconnected.

## Home Assistant

Normal umbrelOS setup no longer requires an environment variable or SSH. Open **Home Assistant** inside 3D Print Cost and enter the base URL, sensor entity id and Long-Lived Access Token there.

The token is stored as a separate persistent secret file with restrictive permissions. It is not stored in SQLite, is never displayed back in the UI and is excluded from the app's JSON business-data backup. For ordinary Docker deployments, `HOME_ASSISTANT_TOKEN` remains an optional advanced override.

The integration performs only GET requests. It supports cumulative energy sensors (`kWh`/`Wh`) and power-history sensors (`W`/`kW`). New v0.13+ quote snapshots preserve the quoted kWh basis and electricity tariff so later global tariff changes do not rewrite historical comparisons. The reconciliation result is informational post-print statistics only.

## System Check

Open **Проверка системы** in the sidebar or `/system`. The page reports:

- application version and container architecture;
- whether persistent `DATA_DIR` exists and is writable;
- SQLite reachability, file presence/size and migration status;
- whether Spoolman/Home Assistant are enabled and configured, without exposing integration URLs or secrets;
- Home Assistant token presence/source without ever returning the token value.

The check itself does not contact Spoolman or Home Assistant. A machine-readable copy is available at `/api/system-check`.

## Real umbrelOS validation

`0.9.0-dev.1` completed the first physical Raspberry Pi/umbrelOS validation: Community App installation, `aarch64` System Check, writable persistent `/data`, SQLite/migrations, app-restart persistence and full host-reboot persistence all passed. `0.10.0-dev.1` refreshed the desktop interface. `0.11.0-dev.1` added the ultrawide/4K real-device pass. `0.12.0-dev.1` is the phone-first pass based directly on iPhone screenshots from the physical installation: mobile header/content spacing, safe bottom navigation, compact Settings disclosures and an on-demand add-filament form.

`0.13.0-dev.1` is the current packaged physical-validation build. It adds conservative `.3mf` → local price matching, economics at the actual customer price, client-safe quote copying, immutable post-print electricity reconciliation and snapshot-only price-discipline analytics. The Community App is pinned to `sha256:8a085a84505362b00802a5f611eee6f0ee69a4b5aa7f040803a1b398aa071bc3` and keeps the same persistent `/data` volume.

`0.14.0-dev.1` is source development after that package. Its first change is a safe installable iPhone/Home Screen shell; the Community App package is intentionally not bumped until the new source is tested and a new immutable runtime digest exists.

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

The released package uses a versioned, immutable-digest-pinned GHCR image. Release CI requires the exact pinned image to be anonymously readable because umbrelOS Community App installation does not use GitHub registry credentials. Source development is allowed to move ahead of the last validated package; package manifest/image version alignment and digest pinning remain separate permanent release gates.

## Data ownership

All app-owned state is stored under `DATA_DIR`. Updating the container does not replace the persistent database volume. Historical order snapshots remain stable when global settings, filament prices or later application versions change.
