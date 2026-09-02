# v0.14 physical Umbrel + iPhone validation

Use this checklist only after the intended v0.14 runtime has been installed on the physical Umbrel host **without deleting the existing app data**.

## 1. Server-side preflight from a computer

The repository includes a Python-standard-library-only checker. It performs GET requests against 3D Print Cost itself and never writes orders, SQLite, Spoolman, Home Assistant or Bambuddy.

Windows PowerShell:

```powershell
py tools\validate_v014_host.py http://YOUR-3D-PRINT-COST-URL
```

Linux/macOS:

```bash
python3 tools/validate_v014_host.py http://YOUR-3D-PRINT-COST-URL
```

For a different build, override the expected version:

```bash
python3 tools/validate_v014_host.py http://YOUR-3D-PRINT-COST-URL --expected-version 0.14.0-dev.1
```

A successful run verifies:

- `/healthz` reports `status=ok` and the expected app version;
- dynamic responses carry `Cache-Control: no-store` and `Pragma: no-cache`;
- the web manifest is installable/standalone with root scope and 192/512 icons;
- the shared page shell links the manifest and connectivity helper;
- Dashboard, New Order, Materials, Statistics and System Check return HTTP 200.

Do not continue to phone-specific validation if this preflight fails.

## 2. Existing-data and System Check

On the physical Umbrel install confirm:

- previous settings and orders are still present;
- System Check reports the expected v0.14 version;
- architecture is `aarch64`;
- persistent `/data` is writable;
- SQLite and migrations are OK.

## 3. iPhone Home Screen shell

In Safari open the normal local 3D Print Cost URL and use **Share → Add to Home Screen**.

Confirm:

- the custom app icon is shown;
- the app launches without normal Safari chrome;
- header content stays below the notch/Dynamic Island;
- the bottom navigation is not hidden by the Home indicator;
- Dashboard and New Order remain usable in portrait orientation.

## 4. Connectivity states

Keep the app open on iPhone.

### Device truly offline

Disable all usable network paths (for example Airplane Mode with Wi-Fi off).

Expected result: the global banner shows **`Телефон офлайн.`** immediately.

### Phone online but Umbrel path unavailable

Restore internet/cellular connectivity but make the local/VPN/Tailscale path to Umbrel unavailable.

Expected result: after the health probe fails, the banner shows **`Umbrel недоступен.`** rather than pretending the app is usable.

### Recovery

Restore the working local/VPN path and return the app to the foreground.

Expected result: an immediate `/healthz` probe succeeds and the warning disappears without reloading the page.

## 5. Real-order regression

After the shell/connectivity tests pass, verify the existing v0.13 business workflow still works unchanged:

- import a sliced Bambu Studio `.3mf`;
- confirm conservative local filament auto-match/ambiguity behavior;
- calculate a quote without saving it first;
- save a test order and confirm actual-customer-price economics;
- copy the client-safe quote on iPhone;
- confirm Spoolman stays read-only;
- complete a test order and inspect Home Assistant electricity reconciliation without mutating historical quote fields.

Only after these physical checks pass should the Umbrel Community App package be bumped and pinned to the tested v0.14 immutable digest.
