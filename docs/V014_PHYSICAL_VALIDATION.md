# v0.14 physical Umbrel + iPhone validation

`0.14.0-dev.1` is the current Community App package for real-device validation. The package uses the exact immutable multi-architecture runtime below:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.14.0-dev.1@sha256:ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0
```

For an installation with no business records, install/update the Community App directly from the custom Umbrel store and validate the packaged runtime. The persistent `/data` mount remains in place, but v0.14 does not add a database-schema migration or change pricing formulas.

Hosts that already contain important business records can still use the isolated shadow helper described at the end of this document before updating the live package.

## 0. Install/update the v0.14 Community App

Refresh the custom app store and install/update **3D Print Cost**. The Umbrel manifest and compose package must both report `0.14.0-dev.1`, and the compose image is pinned to the digest above rather than a mutable tag-only reference.

After launch, open **Проверка системы** and confirm the app responds before starting phone-specific checks.

## 1. Server-side preflight from a computer

The repository includes a Python-standard-library-only checker. It performs GET requests against 3D Print Cost itself and never writes orders, SQLite, Spoolman, Home Assistant or Bambuddy.

Point it at the normal URL that Umbrel opens for the installed app. Save the machine-readable JSON report so the exact server-side result can be kept with the physical validation notes.

Windows PowerShell:

```powershell
py tools\validate_v014_host.py http://YOUR-3D-PRINT-COST-URL `
  --json-out v014-host-preflight.json
```

Linux/macOS:

```bash
python3 tools/validate_v014_host.py http://YOUR-3D-PRINT-COST-URL \
  --json-out v014-host-preflight.json
```

A successful run verifies:

- `/healthz` reports `status=ok` and version `0.14.0-dev.1`;
- dynamic responses carry `Cache-Control: no-store` and `Pragma: no-cache`;
- the web manifest is installable/standalone with root scope and 192/512 icons;
- the shared page shell links the manifest and connectivity helper;
- Dashboard, New Order, Materials, Statistics and System Check return HTTP 200.

The optional JSON report is versioned as `3d-print-cost-v014-host-preflight-v1` and records:

- UTC generation time;
- normalized target URL and expected version;
- exact candidate image including immutable digest;
- one pass/fail entry for every server-side check;
- overall `pass` or `fail` result.

The report deliberately excludes HTTP response bodies and headers, cookies, tokens and credentials. Base URLs with embedded `user:password@host` credentials are rejected. A report is still written when an individual server-side check fails, which makes failed physical runs diagnosable without copying raw application responses.

Do not continue to phone-specific validation if this preflight fails. Preserve the JSON report for both passed and failed validation attempts.

## 2. Runtime and System Check

On the installed **v0.14 Community App** confirm:

- System Check reports `0.14.0-dev.1`;
- architecture is `aarch64` on Raspberry Pi;
- persistent `/data` is writable;
- SQLite and migrations are OK;
- Spoolman/Home Assistant configuration status is shown without exposing secrets.

If the installation was empty before the update, creating test orders during this validation is acceptable. They can be deleted after the checks are complete.

## 3. iPhone Home Screen shell

In Safari open the normal 3D Print Cost URL and use **Share → Add to Home Screen**.

Confirm:

- the custom app icon is shown;
- the app launches without normal Safari chrome;
- header content stays below the notch/Dynamic Island;
- the bottom navigation is not hidden by the Home indicator;
- Dashboard and New Order remain usable in portrait orientation.

## 4. Connectivity states

Keep the installed app open on iPhone.

### Device truly offline

Disable all usable network paths (for example Airplane Mode with Wi-Fi off).

Expected result: the global banner shows **`Телефон офлайн.`** immediately.

### Phone online but Umbrel path unavailable

Restore internet/cellular connectivity but make the LAN/VPN/Tailscale path to the Raspberry Pi unavailable while the phone itself remains online.

Expected result: after the health probe fails, the banner shows **`Umbrel недоступен.`** rather than pretending the app is usable.

### Recovery

Restore the working LAN/VPN path and return the app to the foreground.

Expected result: an immediate `/healthz` probe succeeds and the warning disappears without reloading the page.

## 5. Real-order regression

After the shell/connectivity tests pass, verify the existing business workflow:

- import a sliced Bambu Studio `.3mf`;
- confirm conservative local filament auto-match/ambiguity behavior;
- calculate a quote without saving it first;
- save one recommended-price and one discounted test order and confirm actual-customer-price economics;
- copy the client-safe quote on iPhone;
- confirm Spoolman stays read-only;
- complete a test order and inspect Home Assistant electricity reconciliation without mutating historical quote fields.

## 6. Finish

Keep `v014-host-preflight.json` with the validation result. If a real-device defect is found, fix that concrete defect before changing pricing logic or adding unrelated features.

Once the packaged v0.14 passes the Raspberry Pi and iPhone checks, it becomes the validated baseline for subsequent source development.

## Optional: isolated shadow validation for hosts with important existing records

The repository still includes `tools/v014_shadow_validation.py` for a conservative parallel test. It creates a separate snapshot using Python's online `sqlite3.backup()` API, excludes live WAL/SHM files from normal copying, mounts only that snapshot at `/data`, and launches the exact digest-pinned v0.14 image on port `18585` without stopping the installed Community App.

Run it as the normal Umbrel user (UID 1000), not with `sudo`:

```bash
python3 tools/v014_shadow_validation.py start \
  --data-dir /ABSOLUTE/PATH/TO/mikefox-3d-print-cost/data
```

Useful commands:

```bash
python3 tools/v014_shadow_validation.py status
python3 tools/v014_shadow_validation.py stop
python3 tools/v014_shadow_validation.py cleanup /tmp/3d-print-cost-v014-YYYYMMDDTHHMMSSZ
```

Cleanup is fail-closed: it refuses unmarked/tampered directories and refuses to delete a snapshot while the shadow container still exists. Keep port `18585` LAN/VPN-only and do not forward it from the router to the public internet.
