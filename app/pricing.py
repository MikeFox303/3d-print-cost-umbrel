from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from math import ceil
from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import MonthlyPaybackRate, Order

RISK_KEYS = {
    "simple": "risk_simple",
    "normal": "risk_normal",
    "complex": "risk_complex",
    "very_complex": "risk_very_complex",
}

PLATFORM_PREFIX = {
    "direct": "platform_direct",
    "olx_private": "platform_olx_private",
    "olx_business": "platform_olx_business",
}

@dataclass
class PriceBreakdown:
    material: float
    electricity: float
    maintenance: float
    labor: float
    packaging: float
    direct_cost: float
    risk_rate: float
    production_cost: float
    fixed_cost_share: float
    base_cost: float
    payback_rate: float
    planned_payback: float
    recommended_base: float
    tax_rate: float
    platform_percent: float
    platform_fixed: float
    platform_cap: float
    min_margin: float
    target_margin: float
    minimum_price: float
    recommended_price: float
    expected_profit: float

    def to_dict(self):
        return asdict(self)

def _month_diff(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month)

def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def _price_with_margin(base: float, tax: float, platform_pct: float, platform_fixed: float,
                       platform_cap: float, margin: float, minimum_order: float) -> float:
    denom = 1 - tax - platform_pct - margin
    if denom <= 0:
        raise ValueError("Сумма налога, комиссии и маржи должна быть меньше 100%")
    uncapped = (base + platform_fixed) / denom
    fee_uncapped = uncapped * platform_pct + platform_fixed
    if platform_cap > 0 and fee_uncapped > platform_cap:
        denom2 = 1 - tax - margin
        if denom2 <= 0:
            raise ValueError("Сумма налога и маржи должна быть меньше 100%")
        result = (base + platform_cap) / denom2
    else:
        result = uncapped
    return max(minimum_order, result)

def platform_fee(price: float, pct: float, fixed: float, cap: float) -> float:
    fee = price * pct + fixed
    if cap > 0:
        fee = min(fee, cap)
    return fee

def get_or_create_monthly_payback_rate(db: Session, settings: dict[str, object], today: date | None = None) -> float:
    today = today or date.today()
    month = today.strftime("%Y-%m")
    existing = db.query(MonthlyPaybackRate).filter_by(month=month).first()
    if existing:
        return existing.rate

    equipment_cost = float(settings["equipment_cost"])
    start = date.fromisoformat(str(settings["payback_started_at"]))
    first_day = _month_start(today)
    rolling_days = int(settings["payback_rolling_days"])
    rolling_start_dt = datetime.combine(first_day - timedelta(days=rolling_days), datetime.min.time())
    first_day_dt = datetime.combine(first_day, datetime.min.time())

    completed = db.query(Order).filter(
        Order.status == "completed",
        Order.deleted_at.is_(None),
        Order.completed_at.isnot(None),
        Order.completed_at >= rolling_start_dt,
        Order.completed_at < first_day_dt,
    ).all()
    rolling_hours = sum(o.print_minutes for o in completed) / 60.0
    monthly_equivalent = rolling_hours / max(1.0, rolling_days / 30.4375)
    reference_hours = max(float(settings["payback_floor_hours_month"]), monthly_equivalent)

    recovered = db.query(func.coalesce(func.sum(Order.realized_payback), 0.0)).filter(
        Order.status == "completed",
        Order.deleted_at.is_(None),
        Order.completed_at < first_day_dt,
    ).scalar() or 0.0
    remaining = max(0.0, equipment_cost - float(recovered))
    elapsed_months = _month_diff(start, first_day)
    remaining_months = max(1, int(settings["payback_months"]) - elapsed_months)

    if remaining <= 0:
        rate = 0.0
    else:
        raw_rate = remaining / (remaining_months * reference_hours)
        rate = min(float(settings["payback_max_rate"]), max(float(settings["payback_min_rate"]), raw_rate))

    row = MonthlyPaybackRate(
        month=month,
        rate=rate,
        reference_hours=reference_hours,
        remaining_equipment=remaining,
        recovered_before=float(recovered),
    )
    db.add(row)
    db.commit()
    return rate

def calculate_price(
    db: Session,
    settings: dict[str, object],
    *,
    print_minutes: int,
    manual_minutes: int,
    packaging_cost: float,
    complexity: str,
    platform: str,
    target_margin: float,
    materials: list[dict],
    electricity_kwh: float | None = None,
) -> PriceBreakdown:
    hours = max(0, print_minutes) / 60.0
    reserve = float(settings["material_reserve"])
    material = sum(max(0.0, float(m["grams"])) * max(0.0, float(m["price_per_g"])) for m in materials) * (1 + reserve)

    if electricity_kwh is not None and electricity_kwh > 0:
        electricity = electricity_kwh * float(settings["electricity_tariff"])
    else:
        electricity = hours * float(settings["average_power_w"]) / 1000 * float(settings["electricity_tariff"])

    maintenance = hours * float(settings["maintenance_per_hour"])
    labor = max(manual_minutes / 60 * float(settings["labor_per_hour"]), float(settings["labor_min_per_order"]))
    packaging = max(0.0, packaging_cost)
    direct_cost = material + electricity + maintenance + labor + packaging

    risk_rate = float(settings[RISK_KEYS.get(complexity, "risk_normal")])
    production_cost = direct_cost / max(0.01, 1 - risk_rate)

    fixed_monthly = float(settings["fixed_monthly_costs"])
    if bool(settings["include_esv"]):
        fixed_monthly += float(settings["esv_monthly"])
    ref_hours = max(1.0, float(settings["payback_floor_hours_month"]))
    fixed_cost_share = hours * fixed_monthly / ref_hours
    base_cost = production_cost + fixed_cost_share

    payback_rate = get_or_create_monthly_payback_rate(db, settings)
    planned_payback = hours * payback_rate
    recommended_base = base_cost + planned_payback

    prefix = PLATFORM_PREFIX.get(platform, "platform_direct")
    platform_pct = float(settings[f"{prefix}_percent"])
    platform_fixed = float(settings[f"{prefix}_fixed"])
    platform_cap = float(settings[f"{prefix}_cap"])
    tax_rate = float(settings["tax_rate"])
    min_margin = float(settings["min_margin"])
    target_margin = float(target_margin)
    minimum_order = float(settings["minimum_order_price"])

    minimum_price = _price_with_margin(base_cost, tax_rate, platform_pct, platform_fixed, platform_cap, min_margin, minimum_order)
    recommended_price = _price_with_margin(recommended_base, tax_rate, platform_pct, platform_fixed, platform_cap, target_margin, minimum_order)

    fee = platform_fee(recommended_price, platform_pct, platform_fixed, platform_cap)
    expected_profit = recommended_price * (1 - tax_rate) - fee - recommended_base

    return PriceBreakdown(
        material=material,
        electricity=electricity,
        maintenance=maintenance,
        labor=labor,
        packaging=packaging,
        direct_cost=direct_cost,
        risk_rate=risk_rate,
        production_cost=production_cost,
        fixed_cost_share=fixed_cost_share,
        base_cost=base_cost,
        payback_rate=payback_rate,
        planned_payback=planned_payback,
        recommended_base=recommended_base,
        tax_rate=tax_rate,
        platform_percent=platform_pct,
        platform_fixed=platform_fixed,
        platform_cap=platform_cap,
        min_margin=min_margin,
        target_margin=target_margin,
        minimum_price=minimum_price,
        recommended_price=recommended_price,
        expected_profit=expected_profit,
    )

def compute_realized_payback(order: Order, settings: dict[str, object]) -> float:
    if not order.final_price or order.final_price <= 0:
        return 0.0
    import json
    snap = json.loads(order.calc_snapshot_json or "{}")
    tax = float(snap.get("tax_rate", settings["tax_rate"]))
    pct = float(snap.get("platform_percent", 0))
    fixed = float(snap.get("platform_fixed", 0))
    cap = float(snap.get("platform_cap", 0))
    target_margin = float(snap.get("target_margin", order.target_margin))
    fee = platform_fee(order.final_price, pct, fixed, cap)
    base_cost = float(snap.get("base_cost", order.production_cost))
    surplus_after_cost = max(0.0, order.final_price * (1 - tax) - fee - base_cost)
    available_for_payback = max(0.0, surplus_after_cost - order.final_price * target_margin)
    planned = float(order.planned_payback)
    base_realized = min(planned, available_for_payback)
    extra = max(0.0, available_for_payback - planned)
    return base_realized + extra * float(settings["extra_profit_payback_share"])

def round_customer_price(value: float) -> float:
    return float(ceil(value / 10.0) * 10)
