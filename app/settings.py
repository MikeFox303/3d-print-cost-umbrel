from __future__ import annotations

import json
from datetime import date
from sqlalchemy.orm import Session
from .models import Setting

DEFAULTS: dict[str, object] = {
    "equipment_cost": 66797.0,
    "payback_months": 12,
    "payback_started_at": date.today().isoformat(),
    "payback_floor_hours_month": 120.0,
    "payback_min_rate": 15.0,
    "payback_max_rate": 30.0,
    "payback_rolling_days": 90,
    "extra_profit_payback_share": 0.50,
    "material_reserve": 0.02,
    "electricity_tariff": 4.32,
    "average_power_w": 180.0,
    "maintenance_per_hour": 4.0,
    "labor_per_hour": 100.0,
    "labor_min_per_order": 25.0,
    "minimum_order_price": 300.0,
    "tax_rate": 0.06,
    "min_margin": 0.20,
    "target_margin": 0.35,
    "fixed_monthly_costs": 0.0,
    "include_esv": False,
    "esv_monthly": 1902.34,
    "risk_simple": 0.02,
    "risk_normal": 0.05,
    "risk_complex": 0.10,
    "risk_very_complex": 0.20,
    "platform_direct_percent": 0.0,
    "platform_direct_fixed": 0.0,
    "platform_direct_cap": 0.0,
    "platform_olx_private_percent": 0.02,
    "platform_olx_private_fixed": 20.0,
    "platform_olx_private_cap": 499.0,
    "platform_olx_business_percent": 0.03,
    "platform_olx_business_fixed": 20.0,
    "platform_olx_business_cap": 499.0,
    "spoolman_enabled": False,
    "spoolman_url": "http://spoolman.local:7912",
    "home_assistant_enabled": False,
    "home_assistant_url": "http://homeassistant.local:8123",
    "home_assistant_energy_entity": "",
}

def _encode(v: object) -> str:
    return json.dumps(v, ensure_ascii=False)

def _decode(raw: str):
    return json.loads(raw)

def ensure_defaults(db: Session) -> None:
    existing = {x.key for x in db.query(Setting.key).all()}
    changed = False
    for key, value in DEFAULTS.items():
        if key not in existing:
            db.add(Setting(key=key, value=_encode(value)))
            changed = True
    if changed:
        db.commit()

def get_settings(db: Session) -> dict[str, object]:
    ensure_defaults(db)
    rows = db.query(Setting).all()
    result = dict(DEFAULTS)
    for row in rows:
        try:
            result[row.key] = _decode(row.value)
        except Exception:
            result[row.key] = row.value
    return result

def set_setting(db: Session, key: str, value: object) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=_encode(value))
        db.add(row)
    else:
        row.value = _encode(value)
    db.commit()
