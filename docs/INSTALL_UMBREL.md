# Install and verify on umbrelOS

This runbook tracks the **real-device** verification of 3D Print Cost. The current Community App release is `0.11.0-dev.1`.

The repository and container are checked in CI for `linux/amd64` and `linux/arm64`. A successful authenticated GitHub Actions push is not enough: umbrelOS must also be able to pull the exact pinned image **anonymously**.

## Expected package

Community App Store repository:

```text
https://github.com/MikeFox303/3d-print-cost-umbrel
```

Expected app version:

```text
0.11.0-dev.1
```

Pinned runtime image:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.11.0-dev.1@sha256:898e165c8d66710959ebf883b23a946dd1ed86c22e5a27318b7781b251f827df
```

## 0. Release installability gate

Before attempting an install or update, the exact pinned GHCR image must be publicly readable without GitHub credentials.

The repository has a dedicated **Umbrel installability** workflow. Its `anonymous GHCR pull` job reads the exact image reference from `mikefox-3d-print-cost/docker-compose.yml`, explicitly uses anonymous registry access, and verifies the manifest. Separate runtime-smoke jobs start the application on both amd64 and arm64 with persistent `/data`, migrations and `/healthz`.

A release is not considered installable while any of these jobs is red.

The first physical `0.9.0-dev.1` install exposed a private-GHCR failure (`401 Unauthorized`). The GHCR package has since been made Public and anonymous-pull validation is now a permanent release gate.

## 1. Add or refresh the Community App Store

Use the Community App Store management UI in umbrelOS and add, or refresh, this GitHub repository:

```text
https://github.com/MikeFox303/3d-print-cost-umbrel
```

Find **3D Print Cost** and confirm the listing shows version `0.11.0-dev.1` before installing/updating.

Do not copy compose files manually into Umbrel and do not add a Home Assistant token through SSH for the normal installation flow.

## 2. Install/update and open the app

Install or update **3D Print Cost** from the Community Store and open it from the Umbrel tile.

Umbrel `app_proxy` fronts the internal application port `8080`; the Community App manifest exposes the app on port `8585`.

The persistent database is mounted from `${APP_DATA_DIR}/data`, so replacing the application image does not replace `3d-cost.db`.

## 3. Run System Check

Open **Проверка системы** in the sidebar or `/system`.

Expected critical results on Raspberry Pi:

| Check | Expected result |
|---|---|
| Version | `0.11.0-dev.1` |
| Architecture | ARM64 (`aarch64` or `arm64`) |
| Persistent data | writable |
| SQLite | reachable |
| Migrations | up to date |
| Secrets exposed | No |
| Diagnostic network requests | No |

The JSON equivalent is available at `/api/system-check`. It intentionally does not return Home Assistant token values or integration URLs and does not contact Spoolman/Home Assistant.

## 4. Persistence status

Persistence was already verified on the physical Umbrel host using `0.9.0-dev.1`:

- app restart: PASS;
- full umbrelOS/Raspberry Pi reboot: PASS;
- SQLite/settings value survived both;
- the temporary setting was then reverted.

For `0.11`, confirm after update that existing settings/data are still present. There is no schema migration in this UI-only release and the same `${APP_DATA_DIR}/data` mount is retained.

## 5. Verify real-device interface

At normal browser zoom on the wide desktop display, verify:

- the content workspace is substantially wider than `0.10`;
- sidebar/navigation and System Check text are comfortably readable;
- dashboard cards use more horizontal space without becoming excessively tall;
- the Materials form and Spoolman panel scale proportionally;
- the empty local-material database message spans the full available material grid;
- phone/tablet layout remains compact and usable.

Capture fresh screenshots of Dashboard, Materials and System Check after the update so further tuning is based on the real rendered result.

## 6. Verify Bambu Studio import

Slice a small disposable model in Bambu Studio and import the sliced `.3mf` into the quote workflow.

Confirm that the preview detects plate print time and per-filament grams before saving an order. The importer only reads `Metadata/slice_info.config`; the uploaded file is not retained and Bambuddy is not involved.

## 7. Verify Spoolman boundary

Enable/configure Spoolman from the app and read a spool snapshot.

Confirm that 3D Print Cost can read remaining weight/purchase-price data required for a quote. Then confirm that no spool inventory is changed by opening, previewing, saving or completing a test quote. Bambuddy/Spoolman remain responsible for their own material accounting.

## 8. Verify Home Assistant boundary

Open **Home Assistant** inside 3D Print Cost and configure the base URL, energy/power entity and Long-Lived Access Token from the browser.

Return to **Проверка системы**. It should report the token as configured without displaying its value.

For a completed disposable order, request the post-print energy statistic and confirm that the saved customer quote is not rewritten. The integration is GET-only.

Export the app JSON backup and confirm the Home Assistant token value is absent from that backup.

## 9. Real-device verification record

Current known result:

```text
Hardware: Raspberry Pi / physical umbrelOS host
0.9.0-dev.1 Community App install: PASS
Anonymous GHCR pull: PASS
Architecture shown by System Check: aarch64
Persistent data writable: PASS
SQLite reachable: PASS
Migrations up to date: PASS
App restart persistence: PASS
Host reboot persistence: PASS
0.10.0-dev.1 interface/update validation: PASS — screenshots captured
0.11.0-dev.1 ultrawide interface validation: PENDING
Bambu .3mf import: PENDING
Spoolman read-only test: PENDING
Home Assistant GET-only test: PENDING
```

## Recovery rule

If an install/update behaves unexpectedly, determine the boundary before editing anything manually:

1. image pull — verify anonymous GHCR gate;
2. runtime — inspect container startup/migrations/health;
3. application opens — use **System Check**;
4. persistent data — do not delete/recreate `/data` while diagnosing an interface or image issue.
