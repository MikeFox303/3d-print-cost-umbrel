import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Order
from app.pricing import calculate_price, compute_realized_payback, evaluate_customer_price
from app.settings import DEFAULTS


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def settings():
    values = dict(DEFAULTS)
    values.update({
        "equipment_cost": 12000.0,
        "payback_started_at": "2026-09-01",
        "payback_months": 12,
        "payback_floor_hours_month": 100.0,
        "payback_min_rate": 10.0,
        "payback_max_rate": 10.0,
        "material_reserve": 0.0,
        "average_power_w": 0.0,
        "maintenance_per_hour": 0.0,
        "labor_per_hour": 0.0,
        "labor_min_per_order": 0.0,
        "minimum_order_price": 0.0,
        "fixed_monthly_costs": 0.0,
        "include_esv": False,
        "tax_rate": 0.06,
        "min_margin": 0.20,
        "target_margin": 0.35,
        "risk_simple": 0.0,
        "risk_normal": 0.0,
        "extra_profit_payback_share": 0.50,
    })
    return values


def quote(db, values):
    return calculate_price(
        db,
        values,
        print_minutes=120,
        manual_minutes=0,
        packaging_cost=0,
        complexity="normal",
        platform="direct",
        target_margin=0.35,
        materials=[{"grams": 100, "price_per_g": 1.0}],
    )


def test_recommended_customer_price_funds_planned_payback_and_target_profit():
    db = make_db()
    breakdown = quote(db, settings())
    actual = evaluate_customer_price(breakdown, breakdown.recommended_price)

    assert actual.payback_contribution == pytest.approx(breakdown.planned_payback)
    assert actual.profit_after_payback == pytest.approx(
        breakdown.recommended_price * breakdown.target_margin
    )
    assert actual.meets_minimum_price is True
    assert actual.meets_recommended_price is True


def test_manual_discount_reduces_payback_before_protected_margin():
    db = make_db()
    breakdown = quote(db, settings())
    discounted = evaluate_customer_price(breakdown, breakdown.minimum_price)

    assert discounted.customer_price < breakdown.recommended_price
    assert discounted.payback_contribution < breakdown.planned_payback
    assert discounted.recommended_gap < 0
    assert discounted.meets_minimum_price is True
    assert discounted.meets_recommended_price is False


def test_price_below_operating_cost_reports_negative_result_without_fake_payback():
    db = make_db()
    breakdown = quote(db, settings())
    actual = evaluate_customer_price(breakdown, 50.0)

    assert actual.operating_result < 0
    assert actual.profit_after_payback < 0
    assert actual.payback_contribution == 0
    assert actual.covers_base_cost is False
    assert actual.meets_minimum_price is False


def test_markup_can_send_only_configured_share_of_extra_profit_to_payback():
    db = make_db()
    breakdown = quote(db, settings())
    recommended = evaluate_customer_price(breakdown, breakdown.recommended_price)
    marked_up = evaluate_customer_price(breakdown, breakdown.recommended_price + 200.0)

    assert marked_up.payback_contribution > recommended.payback_contribution
    assert marked_up.payback_contribution < recommended.payback_contribution + 200.0
    assert marked_up.profit_after_payback > recommended.profit_after_payback


def test_realized_payback_prefers_snapshotted_customer_economics():
    db = make_db()
    values = settings()
    breakdown = quote(db, values)
    actual = evaluate_customer_price(breakdown, breakdown.recommended_price + 100.0)
    snapshot = breakdown.to_dict()
    snapshot["customer_economics"] = actual.to_dict()

    order = Order(
        title="Snapshotted actual price",
        target_margin=breakdown.target_margin,
        final_price=actual.customer_price,
        production_cost=breakdown.production_cost,
        planned_payback=breakdown.planned_payback,
        calc_snapshot_json=json.dumps(snapshot),
    )

    changed_settings = dict(values)
    changed_settings["extra_profit_payback_share"] = 0.0
    assert compute_realized_payback(order, changed_settings) == pytest.approx(actual.payback_contribution)


def test_legacy_snapshot_uses_snapshotted_extra_profit_share_when_present():
    db = make_db()
    values = settings()
    breakdown = quote(db, values)
    price = breakdown.recommended_price + 100.0
    expected = evaluate_customer_price(breakdown, price).payback_contribution

    order = Order(
        title="Legacy-style root snapshot",
        target_margin=breakdown.target_margin,
        final_price=price,
        production_cost=breakdown.production_cost,
        planned_payback=breakdown.planned_payback,
        calc_snapshot_json=json.dumps(breakdown.to_dict()),
    )
    changed_settings = dict(values)
    changed_settings["extra_profit_payback_share"] = 0.0

    assert compute_realized_payback(order, changed_settings) == pytest.approx(expected)
