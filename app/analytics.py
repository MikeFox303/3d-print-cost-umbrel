from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import Order
from .pricing import get_or_create_monthly_payback_rate, platform_fee


CALIBRATION_MIN_SAMPLE = 5


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
    calibration_exact_orders: int
    calibration_legacy_orders: int
    calibration_revenue: float
    calibration_below_recommended: int
    calibration_below_minimum: int
    calibration_average_deviation_uah: float
    calibration_average_deviation_percent: float
    calibration_profit_after_payback: float
    calibration_average_profit_after_payback: float
    calibration_margin_after_payback: float
    calibration_realized_payback: float
    calibration_min_sample: int
    calibration_state: str

    def to_dict(self):
        return asdict(self)


def _month_diff(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month)


def _json_snapshot(order: Order) -> dict:
    try:
        value = json.loads(order.calc_snapshot_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _financial_snapshot(order: Order, settings: dict) -> tuple[float, float]:
    """Return operating surplus and profit after realized equipment payback.

    Operating surplus is what remains from the customer payment after tax,
    platform fees, and the order's snapshotted operating/base cost. It is
    deliberately calculated from the historical snapshot rather than current
    global settings.
    """
    if not order.final_price:
        return 0.0, 0.0
    snap = _json_snapshot(order)
    tax = float(snap.get("tax_rate", settings.get("tax_rate", 0)))
    pct = float(snap.get("platform_percent", 0))
    fixed = float(snap.get("platform_fixed", 0))
    cap = float(snap.get("platform_cap", 0))
    base_cost = float(snap.get("base_cost", order.production_cost or 0))
    fee = platform_fee(float(order.final_price), pct, fixed, cap)
    surplus = max(0.0, float(order.final_price) * (1 - tax) - fee - base_cost)
    after_payback = surplus - float(order.realized_payback or 0)
    return surplus, after_payback


def _actual_price_calibration(order: Order) -> dict | None:
    """Return exact v0.13 actual-price metrics or None for legacy/incomplete data.

    Calibration deliberately refuses to reconstruct old orders from current
    settings. A row is exact only when the persisted customer-economics snapshot
    is complete, internally consistent, and still agrees with the persisted
    final customer price.
    """
    if order.final_price is None:
        return None
    snap = _json_snapshot(order)
    economics = snap.get("customer_economics")
    if not isinstance(economics, dict):
        return None
    required = {
        "customer_price",
        "profit_after_payback",
        "recommended_gap",
        "minimum_gap",
        "meets_recommended_price",
        "meets_minimum_price",
    }
    if not required.issubset(economics):
        return None
    if "recommended_price" not in snap or "minimum_price" not in snap:
        return None

    try:
        customer_price = float(economics["customer_price"])
        final_price = float(order.final_price)
        recommended_price = float(snap["recommended_price"])
        minimum_price = float(snap["minimum_price"])
        recommended_gap = float(economics["recommended_gap"])
        minimum_gap = float(economics["minimum_gap"])
        profit_after_payback = float(economics["profit_after_payback"])
    except (TypeError, ValueError):
        return None

    if customer_price <= 0 or recommended_price <= 0 or minimum_price < 0:
        return None
    if abs(customer_price - final_price) >= 0.005:
        return None
    if abs((customer_price - recommended_price) - recommended_gap) >= 0.005:
        return None
    if abs((customer_price - minimum_price) - minimum_gap) >= 0.005:
        return None
    if bool(economics["meets_recommended_price"]) != (customer_price >= recommended_price):
        return None
    if bool(economics["meets_minimum_price"]) != (customer_price >= minimum_price):
        return None

    return {
        "customer_price": customer_price,
        "recommended_gap": recommended_gap,
        "recommended_gap_percent": recommended_gap / recommended_price,
        "profit_after_payback": profit_after_payback,
        "below_recommended": customer_price < recommended_price,
        "below_minimum": customer_price < minimum_price,
        "realized_payback": float(order.realized_payback or 0.0),
    }


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

    calibration_rows = [
        row
        for order in completed
        if (row := _actual_price_calibration(order)) is not None
    ]
    exact_count = len(calibration_rows)
    legacy_count = len(completed) - exact_count
    calibration_revenue = sum(row["customer_price"] for row in calibration_rows)
    calibration_profit = sum(row["profit_after_payback"] for row in calibration_rows)
    calibration_realized_payback = sum(row["realized_payback"] for row in calibration_rows)
    calibration_below_recommended = sum(1 for row in calibration_rows if row["below_recommended"])
    calibration_below_minimum = sum(1 for row in calibration_rows if row["below_minimum"])
    calibration_avg_deviation_uah = (
        sum(row["recommended_gap"] for row in calibration_rows) / exact_count
        if exact_count else 0.0
    )
    calibration_avg_deviation_percent = (
        sum(row["recommended_gap_percent"] for row in calibration_rows) / exact_count
        if exact_count else 0.0
    )
    calibration_avg_profit = calibration_profit / exact_count if exact_count else 0.0
    calibration_margin = calibration_profit / calibration_revenue if calibration_revenue > 0 else 0.0
    if exact_count == 0:
        calibration_state = "no_data"
    elif exact_count < CALIBRATION_MIN_SAMPLE:
        calibration_state = "small_sample"
    else:
        calibration_state = "enough_data"

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
        calibration_exact_orders=exact_count,
        calibration_legacy_orders=legacy_count,
        calibration_revenue=calibration_revenue,
        calibration_below_recommended=calibration_below_recommended,
        calibration_below_minimum=calibration_below_minimum,
        calibration_average_deviation_uah=calibration_avg_deviation_uah,
        calibration_average_deviation_percent=calibration_avg_deviation_percent,
        calibration_profit_after_payback=calibration_profit,
        calibration_average_profit_after_payback=calibration_avg_profit,
        calibration_margin_after_payback=calibration_margin,
        calibration_realized_payback=calibration_realized_payback,
        calibration_min_sample=CALIBRATION_MIN_SAMPLE,
        calibration_state=calibration_state,
    )
