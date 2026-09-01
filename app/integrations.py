from __future__ import annotations

from urllib.parse import urljoin
import httpx

class ReadOnlySpoolmanClient:
    """Deliberately GET-only client. No write methods exist in this class."""

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    async def list_spools(self) -> list[dict]:
        url = urljoin(self.base_url, "api/v1/spool")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        result = []
        for spool in data:
            filament = spool.get("filament") or {}
            vendor = filament.get("vendor") or {}
            weight = float(filament.get("weight") or 0)
            price = float(filament.get("price") or 0)
            result.append({
                "id": spool.get("id"),
                "name": filament.get("name") or f"Spool #{spool.get('id')}",
                "vendor": vendor.get("name") or "",
                "material": filament.get("material") or "",
                "color_hex": filament.get("color_hex") or "",
                "remaining_weight": spool.get("remaining_weight"),
                "weight": weight or None,
                "price": price or None,
                "price_per_g": (price / weight) if price and weight else None,
                "location": spool.get("location") or "",
                "archived": bool(spool.get("archived")),
            })
        return result
