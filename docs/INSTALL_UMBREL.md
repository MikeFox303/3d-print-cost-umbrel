# Install and verify on umbrelOS

This runbook is for the first **real-device** verification of 3D Print Cost `0.9.0-dev.1`.

The repository and container are checked in CI for `linux/amd64` and `linux/arm64`, but a successful authenticated GitHub Actions push is not proof that umbrelOS can install the image. Community App installation must also be able to pull the pinned container **anonymously**.

## Expected package

Community App Store repository:

```text
https://github.com/MikeFox303/3d-print-cost-umbrel
```

Expected app version:

```text
0.9.0-dev.1
```

Pinned runtime image:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.9.0-dev.1@sha256:32ad05edf930103b69c458af43528bd3f44c4ed3f01c9a97aaacad2f4ad9bd62
```

## 0. Release installability gate

Before attempting a Community App installation, the exact pinned GHCR image must be publicly readable without GitHub credentials.

The repository has a dedicated **Umbrel installability** CI workflow. Its `anonymous GHCR pull` job reads the exact image reference from `mikefox-3d-print-cost/docker-compose.yml`, explicitly logs out of GHCR and inspects the manifest without credentials.

A release is not considered installable while this job is red.

GitHub Container Registry packages created under a personal account are private by default. For a Community App, the package must be changed to **Public** in the container package settings so umbrelOS can pull it without a registry login. GitHub warns that changing a package to Public is irreversible.

Known failure signature:

```text
failed to authorize: failed to fetch anonymous token
401 Unauthorized
```

The first physical install of `0.9.0-dev.1` reproduced exactly this failure before the application container started. If this signature appears, fix GHCR package visibility first; do not edit the Umbrel compose file or application database.

## 1. Add the Community App Store

Use the Community App Store management UI in umbrelOS and add the GitHub repository URL above. Umbrel's official Community App Store template uses this same flow: a Community Store is added by its GitHub URL through the umbrelOS interface.

After the store refreshes, find **3D Print Cost** and confirm the listing shows version `0.9.0-dev.1` before installing.

Do not copy compose files manually into Umbrel and do not add a Home Assistant token through SSH for the normal installation flow.

## 2. Install and open the app

Install **3D Print Cost** from the added Community Store and open it from the Umbrel app tile.

The expected browser entry point is handled by Umbrel `app_proxy`. The application itself listens on port `8080` inside the app network; the Community App manifest exposes it through Umbrel on port `8585`.

If the install fails before an app tile can open, check the `anonymous GHCR pull` gate before debugging application startup.

## 3. Run System Check first

Before creating real business data, open **Проверка системы** in the sidebar or open `/system` inside the app.

Expected critical results:

| Check | Expected result |
|---|---|
| Version | `0.9.0-dev.1` |
| Architecture on Raspberry Pi 5 | ARM64 (`aarch64` or `arm64`) |
| Persistent data | writable |
| SQLite | reachable |
| Migrations | up to date |
| Secrets exposed | No |
| Diagnostic network requests | No |

The JSON equivalent is available at `/api/system-check`. It intentionally does not return Home Assistant token values or configured integration URLs and does not contact Spoolman/Home Assistant.

If any of the three critical checks — persistent storage, SQLite or migrations — is unhealthy, stop the functional test and inspect the app logs before entering real order data.

## 4. Verify persistence

Create only disposable data for this stage:

1. add one local test filament;
2. create one test order;
3. restart the app from umbrelOS;
4. confirm the filament and order are still present;
5. reboot the Umbrel host when convenient;
6. confirm the same data is still present after the host returns.

This checks that `${APP_DATA_DIR}/data` is actually persistent on the real host rather than merely writable during one container lifetime.

## 5. Verify Bambu Studio import

Slice a small disposable model in Bambu Studio and import the sliced `.3mf` into the quote workflow.

Confirm that the preview detects the plate print time and per-filament grams before saving an order. Do not use a valuable production order for this first test.

## 6. Verify Spoolman boundary

Enable/configure Spoolman from the app and read a spool snapshot.

Confirm that 3D Print Cost can read the remaining weight/purchase-price data required for a quote. Then confirm that no spool inventory is changed by opening, previewing, saving or completing a test quote. Bambuddy/Spoolman remain responsible for their own material accounting.

## 7. Verify Home Assistant boundary

Open **Home Assistant** inside 3D Print Cost and configure the base URL, energy/power entity and Long-Lived Access Token from the browser.

Return to **Проверка системы**. It should report the token as configured without displaying its value.

For a completed disposable order, request the post-print energy statistic and confirm that the saved customer quote is not rewritten. The integration is GET-only.

Export the app JSON backup and confirm the Home Assistant token value is absent from that backup.

## 8. Record the device result

Fill this section after the first real installation:

```text
Test date:
umbrelOS version:
Hardware:
App version shown:
Anonymous GHCR pull: PASS / FAIL
Architecture shown by System Check:
Persistent data writable: PASS / FAIL
SQLite reachable: PASS / FAIL
Migrations up to date: PASS / FAIL
App restart persistence: PASS / FAIL
Host reboot persistence: PASS / FAIL
Bambu .3mf import: PASS / FAIL
Spoolman read-only test: PASS / FAIL / NOT CONFIGURED
Home Assistant GET-only test: PASS / FAIL / NOT CONFIGURED
JSON backup excludes HA token: PASS / FAIL / NOT CONFIGURED
Pinned image/digest confirmed: PASS / FAIL / NOT CHECKED
Notes / log errors:
```

Only after the anonymous image pull, critical System Check results, restart persistence and host-reboot persistence pass should the package be considered verified on that physical umbrelOS device.

## Recovery rule for the first test

If the first installation behaves unexpectedly, do not immediately edit the compose file or database in place. Determine the failure boundary first:

1. if the image cannot be pulled anonymously, fix registry visibility;
2. if the image pulls but the container does not become healthy, inspect runtime logs;
3. if the app opens, use **System Check** before changing data or configuration.

This keeps failures reproducible and distinguishes registry, Umbrel packaging, application startup and application-data problems.
