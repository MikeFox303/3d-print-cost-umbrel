# umbrelOS readiness

This document separates **package/CI readiness** from **real umbrelOS runtime verification**.

## Structurally checked in the repository

The Community App package follows the current browser-app pattern:

- app-store id `mikefox` prefixes app id/folder `mikefox-3d-print-cost`;
- manifest uses `manifestVersion: 1` and a browser port/path;
- compose declares `version: "3.7"` and an `app_proxy` service;
- `APP_HOST` is the expected Umbrel service name `mikefox-3d-print-cost_web_1`;
- the web process listens internally on port 8080 and has no raw host port in the Umbrel package;
- persistent application state is under `${APP_DATA_DIR}/data`;
- no privileged mode, host networking, Docker socket or device access is requested;
- runtime image is version-tagged **and digest-pinned** rather than `latest`;
- GitHub Actions builds both `linux/amd64` and `linux/arm64` after automated tests;
- normal Home Assistant setup is browser-first: URL, entity id and token can be entered in the app UI, with no SSH/Docker Compose editing required;
- v0.9 provides a browser-safe System Check for architecture, persistent storage, SQLite, migrations and integration configuration without exposing secrets or contacting external integrations.

The Home Assistant token is kept in `${DATA_DIR}/secrets/home-assistant-token`, not in SQLite, and the app writes it with mode `0600`. The app's JSON business-data backup intentionally excludes this secret. `HOME_ASSISTANT_TOKEN` remains only as an optional advanced Docker override.

## Container publication

Before v0.8 the workflow accidentally kept publishing the raw tag `0.3.0-dev.1` even after the application version advanced. The workflow now reads `app.__version__`, performs an amd64+arm64 build on pull requests without pushing, and publishes the exact application version on `main` when runtime files change. Package/docs-only merges are path-filtered so they do not mutate an already-published version tag. Explicit `v*` tag pushes can still publish release images.

## Published v0.9 image

The successful main build published both `linux/amd64` and `linux/arm64` under:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.9.0-dev.1
```

The immutable multi-architecture digest is:

```text
sha256:32ad05edf930103b69c458af43528bd3f44c4ed3f01c9a97aaacad2f4ad9bd62
```

The Umbrel package is pinned to the combined reference:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.9.0-dev.1@sha256:32ad05edf930103b69c458af43528bd3f44c4ed3f01c9a97aaacad2f4ad9bd62
```

This means an installation resolves the exact tested v0.9 multi-arch manifest instead of whatever a mutable tag might point to later.

## What is NOT verified yet

Repository tests and a successful Docker multi-architecture build are not the same as an actual umbrelOS lifecycle test. Until the package is installed on an umbrelOS machine, we do **not** claim that real-device installation is verified.

The remaining runtime checklist on an actual Umbrel device is:

1. add the custom Community App Store from the repository URL;
2. install `3D Print Cost` through the Umbrel UI;
3. open the web UI through the app tile/app_proxy;
4. open **Проверка системы** (`/system`) and verify `0.9.0-dev.1`, writable persistent data, reachable SQLite and up-to-date migrations;
5. on Raspberry Pi 5 confirm the reported architecture is ARM64 (`aarch64`/`arm64` depending on runtime naming);
6. create a disposable test order and local filament;
7. restart the app and verify SQLite persistence;
8. reboot/restart the Umbrel host/app stack and verify persistence again;
9. import a small sliced `.3mf` and verify quote preview;
10. configure Spoolman read-only and confirm no inventory write occurs;
11. configure Home Assistant in the browser and verify only energy history/state is read;
12. return to System Check and confirm integration configuration is shown without exposing the Home Assistant token value;
13. export a JSON backup and verify the Home Assistant token is absent;
14. inspect app logs for migration/startup errors if any System Check item is not healthy;
15. confirm the installed package uses the pinned v0.9 multi-arch digest above.

Only after these steps should Raspberry Pi 5 / arm64 runtime verification be marked complete.
