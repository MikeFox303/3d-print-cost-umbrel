# v0.14 physical Umbrel + iPhone validation

The preferred v0.14 validation path keeps the physically validated v0.13 Community App running unchanged. A separate **shadow container** uses the immutable v0.14 candidate and a copied data snapshot on another LAN port.

Candidate image:

```text
ghcr.io/mikefox303/3d-print-cost-umbrel:0.14.0-dev.1@sha256:ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0
```

## 0. Start the isolated v0.14 shadow on the Raspberry Pi

Run the helper as the normal Umbrel user (UID 1000), **not with `sudo`**. Supply the real installed app data directory that contains `3d-cost.db`.

```bash
python3 tools/v014_shadow_validation.py start \
  --data-dir /ABSOLUTE/PATH/TO/mikefox-3d-print-cost/data
```

Default validation port: `18585`.

The helper deliberately does all of the following before v0.14 starts:

- requires an explicit live data path and verifies `3d-cost.db` exists;
- creates a separate snapshot under `/tmp` by default;
- copies SQLite through Python's online `sqlite3.backup()` API and runs `PRAGMA integrity_check`;
- excludes the source DB's WAL/SHM files from ordinary file copying;
- copies the other persistent files into the snapshot;
- refuses a snapshot root inside the live `/data` directory;
- pulls the exact digest-pinned v0.14 image above;
- launches a new container named `3d-print-cost-v014-shadow` as UID/GID `1000:1000`;
- mounts **only the snapshot** at `/data:rw`;
- verifies the shadow `/healthz` reports exactly `0.14.0-dev.1`;
- prints one or more `http://<PI-IP>:18585` candidates for iPhone testing.

The installed v0.13 container is not stopped, restarted or edited. Its compose file is not changed, and its live `/data` directory is never mounted into the validation container.

Useful commands:

```bash
python3 tools/v014_shadow_validation.py status
python3 tools/v014_shadow_validation.py stop
```

`stop` removes only the shadow container and leaves its snapshot intact. When validation is completely finished, delete the exact marked snapshot path printed by the tool:

```bash
python3 tools/v014_shadow_validation.py cleanup /tmp/3d-print-cost-v014-YYYYMMDDTHHMMSSZ
```

Cleanup is fail-closed: it refuses unmarked/tampered directories and refuses to delete a snapshot while the shadow container still exists.

Keep port `18585` LAN/VPN-only. Do not forward it from the router to the public internet.

## 1. Server-side preflight from a computer

The repository also includes a Python-standard-library-only checker. It performs GET requests against 3D Print Cost itself and never writes orders, SQLite, Spoolman, Home Assistant or Bambuddy.

Point it at the **shadow URL** printed in step 0. Save the machine-readable JSON report so the exact server-side result can be kept with the physical validation notes.

Windows PowerShell:

```powershell
py tools\validate_v014_host.py http://RASPBERRY-PI-IP:18585 `
  --json-out v014-host-preflight.json
```

Linux/macOS:

```bash
python3 tools/validate_v014_host.py http://RASPBERRY-PI-IP:18585 \
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

## 2. Snapshot data and System Check

On the **shadow v0.14** confirm:

- the expected previous settings and orders are present from the snapshot;
- System Check reports `0.14.0-dev.1`;
- architecture is `aarch64`;
- shadow `/data` is writable;
- SQLite and migrations are OK.

Changes made during this validation belong only to the copied shadow snapshot. They are not expected to appear in the still-running v0.13 Community App.

## 3. iPhone Home Screen shell

In Safari open the shadow URL and use **Share → Add to Home Screen**.

Confirm:

- the custom app icon is shown;
- the app launches without normal Safari chrome;
- header content stays below the notch/Dynamic Island;
- the bottom navigation is not hidden by the Home indicator;
- Dashboard and New Order remain usable in portrait orientation.

## 4. Connectivity states

Keep the shadow app open on iPhone.

### Device truly offline

Disable all usable network paths (for example Airplane Mode with Wi-Fi off).

Expected result: the global banner shows **`Телефон офлайн.`** immediately.

### Phone online but Umbrel path unavailable

Restore internet/cellular connectivity but make the LAN/VPN/Tailscale path to the Raspberry Pi unavailable while the phone itself remains online.

Expected result: after the health probe fails, the banner shows **`Umbrel недоступен.`** rather than pretending the app is usable.

### Recovery

Restore the working LAN/VPN path and return the app to the foreground.

Expected result: an immediate `/healthz` probe succeeds and the warning disappears without reloading the page.

## 5. Real-order regression on the snapshot

After the shell/connectivity tests pass, verify the existing v0.13 business workflow still works unchanged inside the shadow copy:

- import a sliced Bambu Studio `.3mf`;
- confirm conservative local filament auto-match/ambiguity behavior;
- calculate a quote without saving it first;
- save a test order and confirm actual-customer-price economics;
- copy the client-safe quote on iPhone;
- confirm Spoolman stays read-only;
- complete a test order and inspect Home Assistant electricity reconciliation without mutating historical quote fields.

These test writes affect the shadow snapshot only. The live v0.13 order ledger remains the comparison/control copy.

## 6. Finish and promote only after results are known

Stop the shadow container first:

```bash
python3 tools/v014_shadow_validation.py stop
```

Preserve its snapshot and `v014-host-preflight.json` until any failed checks have been diagnosed and the physical iPhone results are recorded. Delete the snapshot only with the marker-validated `cleanup` command when it is no longer useful.

Only after the physical v0.14 checks pass should the Umbrel Community App package be promoted from the validated v0.13 image to the tested v0.14 immutable digest.
