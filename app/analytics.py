from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import Order
from .pricing import get_or_create_monthly_payback_rate, platform_fee


@dataclass
class BusinessStats:
    completed_total: int
    completed_month: int
    revenue_month: float
    commercial_hours_month: float
    average_order_month: float
    operating_surplus_month: float
    realized_payback_month: float
    profit_after_payback_month: float
    recovered_total: float
    equipment_cost: float
    equipment_remaining: float
    payback_percent: float
    current_payback_rate: float
    rolling_days: int
    rolling_hours: float
    rolling_hours_monthly_equivalent: float
    rolling_payback: float
    rolling_payback_monthly_equivalent: float
    projected_months_remaining: float | None
    target_months_remaining: int
    forecast_state: str

    def to_dict(self):
        return asdict(self)


def _month_diff(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month)


def _financial_snapshot(order: Order, settings: dict) -> tuple[float, float]:
    """Return operating surplus and profit after realized equipment payback.

    Operating surplus is what remains from the customer payment after tax,
    platform fees, and the order's snapshotted operating/base cost. It is
    deliberately calculated from the historical snapshot rather than current
    global settings.
    """
    if not order.final_price:
        return 0.0, 0.0
    try:
        snap = json.loads(order.calc_snapshot_json or "{}")
    except json.JSONDecodeError:
        snap = {}
    tax = float(snap.get("tax_rate", settings.get("tax_rate", 0)))
    pct = float(snap.get("platform_percent", 0))
    fixed = float(snap.get("platform_fixed", 0))
    cap = float(snap.get("platform_cap", 0))
    base_cost = float(snap.get("base_cost", order.production_cost or 0))
    fee = platform_fee(float(order.final_price), pct, fixed, cap)
    surplus = max(0.0, float(order.final_price) * (1 - tax) - fee - base_cost)
    after_payback = surplus - float(order.realized_payback or 0)
    return surplus, after_payback


def build_business_stats(
    db: Session,
    settings: dict,
    today: date | None = None,
) -> BusinessStats:
    today = today or date.today()
    month_start = datetime(today.year, today.month, 1)
    rolling_days = int(settings.get("payback_rolling_days", 90))
    rolling_start = datetime.combine(today - timedelta(days=rolling_days), datetime.min.time())
    now_limit = datetime.combine(today + timedelta(days=1), datetime.min.time())

    completed = (
        db.query(Order)
        .filter(
            Order.status == "completed",
            Order.deleted_at.is_(None),
            Order.completed_at.isnot(None),
        )
        .all()
    )
    month_orders = [o for o in completed if month_start <= o.completed_at < now_limit]
    rolling_orders = [o for o in completed if rolling_start <= o.completed_at < now_limit]

    revenue_month = sum(float(o.final_price or 0) for o in month_orders)
    month_hours = sum(o.print_minutes for o in month_orders) / 60.0
    realized_month = sum(float(o.realized_payback or 0) for o in month_orders)
    recovered_total = sum(float(o.realized_payback or 0) for o in completed)

    operating_surplus_month = 0.0
    profit_after_payback_month = 0.0
    for order in month_orders:
        surplus, after = _financial_snapshot(order, settings)
        operating_surplus_month += surplus
        profit_after_payback_month += after

    rolling_hours = sum(o.print_minutes for o in rolling_orders) / 60.0
    rolling_payback = sum(float(o.realized_payback or 0) for o in rolling_orders)
    window_months = max(1.0, rolling_days / 30.4375)
    rolling_hours_monthly = rolling_hours / window_months
    rolling_payback_monthly = rolling_payback / window_months

    equipment_cost = float(settings.get("equipment_cost", 0))
    remaining = max(0.0, equipment_cost - recovered_total)
    payback_percent = min(100.0, recovered_total / equipment_cost * 100) if equipment_cost else 100.0
    projected = remaining / rolling_payback_monthly if rolling_payback_monthly > 0 else None

    start = date.fromisoformat(str(settings.get("payback_started_at", today.isoformat())))
    elapsed = _month_diff(start, today)
    target_remaining = max(0, int(settings.get("payback_months", 12)) - elapsed)
    if remaining <= 0:
        forecast_state = "paid"
    elif projected is None:
        forecast_state = "no_data"
    elif target_remaining > 0 and projected <= target_remaining:
        forecast_state = "on_track"
    else:
        forecast_state = "behind"

    return BusinessStats(
        completed_total=len(completed),
        completed_month=len(month_orders),
        revenue_month=revenue_month,
        commercial_hours_month=month_hours,
        average_order_month=(revenue_month / len(month_orders)) if month_orders else 0.0,
        operating_surplus_month=operating_surplus_month,
        realized_payback_month=realized_month,
        profit_after_payback_month=profit_after_payback_month,
        recovered_total=recovered_total,
        equipment_cost=equipment_cost,
        equipment_remaining=remaining,
        payback_percent=payback_percent,
        current_payback_rate=get_or_create_monthly_payback_rate(db, settings, today),
        rolling_days=rolling_days,
        rolling_hours=rolling_hours,
        rolling_hours_monthly_equivalent=rolling_hours_monthly,
        rolling_payback=rolling_payback,
        rolling_payback_monthly_equivalent=rolling_payback_monthly,
        projected_months_remaining=projected,
        target_months_remaining=target_remaining,
        forecast_state=forecast_state,
    )
