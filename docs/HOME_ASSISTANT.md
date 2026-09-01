# Home Assistant read-only energy statistics

The Home Assistant integration is intentionally **post-print and GET-only**. It never participates in the pre-print quote and never changes Home Assistant or a saved order.

## Credentials

The Long-Lived Access Token is read from the container environment variable:

`HOME_ASSISTANT_TOKEN`

It is not stored in SQLite, not returned by the UI, and not included in JSON backups or pre-restore safety backups.

The local database stores only non-secret configuration:

- `home_assistant_enabled`
- `home_assistant_url`
- `home_assistant_energy_entity`

## Requests

The client has only HTTP GET operations:

- `GET /api/states/<entity_id>` to read the sensor unit;
- `GET /api/history/period/<start>` to read sensor history for the print window.

No service calls, state writes, config writes, POST, PUT, PATCH or DELETE requests exist in this integration.

## Supported sensor types

### Cumulative energy

Units: `kWh` or `Wh`.

The app sums positive changes through the period. If the meter decreases (for example after a device reboot or daily reset), the new value is treated as the start of a new segment instead of producing negative consumption.

### Power history

Units: `W` or `kW`.

The app integrates the history using trapezoidal integration and returns kWh.

## Print window

For a completed order:

- end = `completed_at`;
- start = `completed_at - print_minutes`.

This intentionally uses the same Bambu Studio duration snapshot that was used for the quote. The API returns `window_source` so the approximation is explicit.

## Historical integrity

The response includes actual kWh, the order's original/estimated kWh, the difference, tariff and actual electricity cost. The response also sets `persisted: false`.

No value is written back into `Order.electricity_kwh`, `production_cost`, `calc_snapshot_json`, final price, payback or other historical fields.
