from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote, urljoin

import httpx


class ReadOnlySpoolmanClient:
    """Deliberately GET-only Spoolman client.

    This class intentionally has no POST/PATCH/PUT/DELETE helpers. The app can read
    current inventory for quoting, but Bambuddy/Spoolman remain solely responsible
    for inventory accounting and deductions.
    """

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    @staticmethod
    def normalize_spool(spool: dict) -> dict:
        filament = spool.get("filament") or {}
        vendor = filament.get("vendor") or {}

        # Spoolman allows a price override on the individual spool. Its own UI falls
        # back to filament.price when spool.price is unset. Do the same here.
        spool_price = spool.get("price")
        filament_price = filament.get("price")
        effective_price = spool_price if spool_price is not None else filament_price

        # For a spool-specific purchase price, initial_weight is the most accurate
        # denominator. Fall back to the nominal full-spool filament weight.
        initial_weight = spool.get("initial_weight")
        filament_weight = filament.get("weight")
        effective_weight = initial_weight if initial_weight not in (None, 0) else filament_weight

        price = float(effective_price) if effective_price is not None else None
        weight = float(effective_weight) if effective_weight not in (None, 0) else None
        price_per_g = (price / weight) if price is not None and weight else None

        return {
            "id": spool.get("id"),
            "name": filament.get("name") or f"Spool #{spool.get('id')}",
            "vendor": vendor.get("name") or "",
            "material": filament.get("material") or "",
            "color_hex": filament.get("color_hex") or "",
            "remaining_weight": spool.get("remaining_weight"),
            "initial_weight": initial_weight,
            "nominal_weight": filament_weight,
            "price": price,
            "price_source": "spool" if spool_price is not None else ("filament" if filament_price is not None else None),
            "price_per_g": price_per_g,
            "location": spool.get("location") or "",
            "archived": bool(spool.get("archived")),
        }

    async def list_spools(self) -> list[dict]:
        url = urljoin(self.base_url, "api/v1/spool")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        return [self.normalize_spool(spool) for spool in data]


class HomeAssistantReadOnlyError(ValueError):
    pass


class ReadOnlyHomeAssistantClient:
    """GET-only Home Assistant client for post-print energy statistics.

    The token is supplied by the caller (normally HOME_ASSISTANT_TOKEN) and is never
    persisted by this client. There are deliberately no write methods.
    """

    ENERGY_UNITS = {"kWh", "Wh"}
    POWER_UNITS = {"W", "kW"}

    def __init__(self, base_url: str, token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token.strip()
        self.timeout = timeout
        if not self.token:
            raise HomeAssistantReadOnlyError("HOME_ASSISTANT_TOKEN не задан.")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_time(raw: str) -> datetime:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)

    @staticmethod
    def _numeric_samples(history: list[dict]) -> list[tuple[datetime, float]]:
        samples: list[tuple[datetime, float]] = []
        for item in history:
            raw_state = item.get("state")
            raw_time = item.get("last_changed") or item.get("last_updated")
            if raw_state in (None, "unknown", "unavailable", "") or not raw_time:
                continue
            try:
                value = float(raw_state)
                moment = ReadOnlyHomeAssistantClient._parse_time(raw_time)
            except (TypeError, ValueError):
                continue
            samples.append((moment, value))
        samples.sort(key=lambda row: row[0])
        return samples

    @staticmethod
    def energy_from_samples(
        samples: list[tuple[datetime, float]],
        unit: str,
        start: datetime,
        end: datetime,
    ) -> float:
        if len(samples) < 1:
            raise HomeAssistantReadOnlyError("Home Assistant не вернул числовых значений сенсора за период печати.")
        start = ReadOnlyHomeAssistantClient._utc(start)
        end = ReadOnlyHomeAssistantClient._utc(end)
        if end <= start:
            raise HomeAssistantReadOnlyError("Некорректное окно времени печати.")

        if unit in ReadOnlyHomeAssistantClient.ENERGY_UNITS:
            values = [value for _, value in samples]
            if len(values) < 2:
                raise HomeAssistantReadOnlyError("Для energy-сенсора нужно минимум два значения истории.")
            total = 0.0
            previous = values[0]
            for current in values[1:]:
                if current >= previous:
                    total += current - previous
                else:
                    # total_increasing sensors may reset (device reboot/daily meter).
                    total += max(current, 0.0)
                previous = current
            return total / 1000.0 if unit == "Wh" else total

        if unit in ReadOnlyHomeAssistantClient.POWER_UNITS:
            factor = 1000.0 if unit == "kW" else 1.0
            points = [(max(start, min(end, t)), value * factor) for t, value in samples if t <= end]
            if not points:
                raise HomeAssistantReadOnlyError("Нет power-данных внутри окна печати.")
            # Collapse duplicate/clamped timestamps, keeping the newest state.
            collapsed: list[tuple[datetime, float]] = []
            for point in points:
                if collapsed and point[0] == collapsed[-1][0]:
                    collapsed[-1] = point
                else:
                    collapsed.append(point)
            if collapsed[0][0] > start:
                collapsed.insert(0, (start, collapsed[0][1]))
            if collapsed[-1][0] < end:
                collapsed.append((end, collapsed[-1][1]))
            watt_hours = 0.0
            for (t0, p0), (t1, p1) in zip(collapsed, collapsed[1:]):
                hours = max(0.0, (t1 - t0).total_seconds() / 3600.0)
                watt_hours += ((p0 + p1) / 2.0) * hours
            return watt_hours / 1000.0

        raise HomeAssistantReadOnlyError(
            f"Неподдерживаемая единица сенсора {unit!r}. Нужна kWh, Wh, W или kW."
        )

    async def _get(self, path: str, *, params: dict | None = None):
        url = urljoin(self.base_url, path)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()

    async def measure_energy(self, entity_id: str, start: datetime, end: datetime) -> dict:
        entity_id = entity_id.strip()
        if not entity_id or "." not in entity_id:
            raise HomeAssistantReadOnlyError("Не задан корректный Home Assistant entity_id.")
        state = await self._get("api/states/" + quote(entity_id, safe="."))
        unit = str((state.get("attributes") or {}).get("unit_of_measurement") or "")

        start_utc = self._utc(start)
        end_utc = self._utc(end)
        history = await self._get(
            "api/history/period/" + quote(start_utc.isoformat(), safe=""),
            params={
                "filter_entity_id": entity_id,
                "end_time": end_utc.isoformat(),
                "minimal_response": "true",
                "no_attributes": "true",
            },
        )
        rows = history[0] if isinstance(history, list) and history and isinstance(history[0], list) else []
        samples = self._numeric_samples(rows)
        kwh = self.energy_from_samples(samples, unit, start_utc, end_utc)
        return {
            "entity_id": entity_id,
            "sensor_unit": unit,
            "mode": "energy_delta" if unit in self.ENERGY_UNITS else "power_integral",
            "start": start_utc.isoformat(),
            "end": end_utc.isoformat(),
            "samples": len(samples),
            "kwh": max(0.0, kwh),
        }
