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
- normal Home Assistant setup is browser-first: URL, entity id and token can be entered in the app UI, with no SSH/Docker Compose editing required.

The Home Assistant token is kept in `${DATA_DIR}/secrets/home-assistant-token`, not in SQLite, and the app writes it with mode `0600`. The app's JSON business-data backup intentionally excludes this secret. `HOME_ASSISTANT_TOKEN` remains only as an optional advanced Docker override.

## Container publication

Before v0.8 the workflow accidentally kept publishing the raw tag `0.3.0-dev.1` even after the application version advanced. v0.8 fixes this: the workflow reads `app.__version__`, performs an amd64+arm64 build on pull requests without pushing, and publishes the exact application version on `main` when runtime files change. Package/docs-only merges are path-filtered so they do not mutate an already-published version tag. Explicit `v*` tag pushes can still publish release images.

## Published v0.8 image

The successful main build published both `linux/amd64` and `linux/arm64` under:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.8.0-dev.1
```

The immutable multi-architecture digest is:

```text
sha256:06304d09ffe55b52fa74e58431fd90d29a31e42723a27f8a1e97d76d95353c7f
```

The Umbrel package is pinned to the combined reference:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.8.0-dev.1@sha256:06304d09ffe55b52fa74e58431fd90d29a31e42723a27f8a1e97d76d95353c7f
```

This means an installation resolves the exact tested v0.8 multi-arch manifest instead of whatever a mutable tag might point to later.

## What is NOT verified yet

Repository tests and a successful Docker multi-architecture build are not the same as an actual umbrelOS lifecycle test. Until the package is installed on an umbrelOS machine, we do **not** claim that real-device installation is verified.

The remaining runtime checklist on an actual Umbrel device is:

1. add the custom Community App Store from the repository URL;
2. install `3D Print Cost` through the Umbrel UI;
3. open the web UI through the app tile/app_proxy;
4. create a disposable test order and local filament;
5. restart the app and verify SQLite persistence;
6. reboot/restart the Umbrel host/app stack and verify persistence again;
7. import a small sliced `.3mf` and verify quote preview;
8. configure Spoolman read-only and confirm no inventory write occurs;
9. configure Home Assistant in the browser and verify only energy history/state is read;
10. export a JSON backup and verify the Home Assistant token is absent;
11. inspect app logs for migration/startup errors;
12. confirm the running architecture/image digest matches the pinned multi-arch digest above.

Only after these steps should Raspberry Pi 5 / arm64 runtime verification be marked complete.
