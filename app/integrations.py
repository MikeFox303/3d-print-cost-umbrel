from __future__ import annotations

from urllib.parse import urljoin
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
