import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Order
from app.pricing import (
    _price_with_margin,
    calculate_price,
    compute_realized_payback,
    get_or_create_monthly_payback_rate,
    platform_fee,
)
from app.settings import DEFAULTS


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def isolated_settings():
    settings = dict(DEFAULTS)
    settings.update({
        "equipment_cost": 0.0,
        "payback_started_at": "2026-09-01",
        "payback_months": 12,
        "payback_floor_hours_month": 100.0,
        "payback_min_rate": 0.0,
        "payback_max_rate": 1000.0,
        "material_reserve": 0.0,
        "average_power_w": 0.0,
        "maintenance_per_hour": 0.0,
        "labor_per_hour": 0.0,
        "labor_min_per_order": 0.0,
        "minimum_order_price": 0.0,
        "fixed_monthly_costs": 0.0,
        "include_esv": False,
        "tax_rate": 0.0,
        "min_margin": 0.0,
        "target_margin": 0.0,
        "risk_simple": 0.0,
        "risk_normal": 0.0,
        "risk_complex": 0.10,
        "risk_very_complex": 0.20,
    })
    return settings


def test_risk_uses_expected_success_cost_multiplier():
    db = make_db()
    settings = isolated_settings()
    result = calculate_price(
        db,
        settings,
        print_minutes=60,
        manual_minutes=0,
        packaging_cost=0,
        complexity="complex",
        platform="direct",
        target_margin=0,
        materials=[{"grams": 100, "price_per_g": 1.0}],
    )
    assert result.direct_cost == pytest.approx(100.0)
    assert result.production_cost == pytest.approx(100.0 / 0.90)


def test_material_reserve_is_applied_once():
    db = make_db()
    settings = isolated_settings()
    settings["material_reserve"] = 0.02
    result = calculate_price(
        db,
        settings,
        print_minutes=60,
        manual_minutes=0,
        packaging_cost=0,
        complexity="normal",
        platform="direct",
        target_margin=0,
        materials=[{"grams": 100, "price_per_g": 1.0}],
    )
    assert result.material == pytest.approx(102.0)
    assert result.production_cost == pytest.approx(102.0)


def test_direct_price_solves_tax_and_margin_from_sale_price():
    price = _price_with_margin(
        base=200.0,
        tax=0.06,
        platform_pct=0.0,
        platform_fixed=0.0,
        platform_cap=0.0,
        margin=0.35,
        minimum_order=0.0,
    )
    assert price == pytest.approx(200.0 / (1 - 0.06 - 0.35))
    assert price * (1 - 0.06 - 0.35) == pytest.approx(200.0)


def test_olx_business_fee_and_margin_before_cap():
    base = 1000.0
    price = _price_with_margin(base, 0.06, 0.03, 20.0, 499.0, 0.35, 0.0)
    fee = platform_fee(price, 0.03, 20.0, 499.0)
    assert fee < 499.0
    assert price * (1 - 0.06 - 0.35) - fee == pytest.approx(base)


def test_olx_business_cap_is_solved_exactly():
    base = 10000.0
    price = _price_with_margin(base, 0.06, 0.03, 20.0, 499.0, 0.35, 0.0)
    fee = platform_fee(price, 0.03, 20.0, 499.0)
    assert fee == pytest.approx(499.0)
    assert price * (1 - 0.06 - 0.35) - fee == pytest.approx(base)


def test_low_load_does_not_exceed_payback_cap():
    db = make_db()
    settings = isolated_settings()
    settings.update({
        "equipment_cost": 60000.0,
        "payback_floor_hours_month": 50.0,
        "payback_min_rate": 5.0,
        "payback_max_rate": 30.0,
    })
    rate = get_or_create_monthly_payback_rate(db, settings, today=date(2026, 9, 1))
    assert rate == 30.0


def test_real_prior_load_reduces_next_month_payback_rate():
    settings = isolated_settings()
    settings.update({
        "equipment_cost": 12000.0,
        "payback_floor_hours_month": 50.0,
        "payback_min_rate": 5.0,
        "payback_max_rate": 50.0,
        "payback_rolling_days": 90,
    })

    empty_db = make_db()
    low_load_rate = get_or_create_monthly_payback_rate(empty_db, settings, today=date(2026, 9, 1))

    busy_db = make_db()
    busy_db.add(Order(
        title="Prior commercial load",
        status="completed",
        print_minutes=300 * 60,
        completed_at=datetime(2026, 8, 15, 12, 0, 0),
        realized_payback=0.0,
    ))
    busy_db.commit()
    busy_rate = get_or_create_monthly_payback_rate(busy_db, settings, today=date(2026, 9, 1))

    assert low_load_rate == pytest.approx(20.0)
    assert busy_rate < low_load_rate
    assert busy_rate >= 5.0


def test_monthly_payback_rate_is_snapshotted_for_fairness():
    db = make_db()
    settings = isolated_settings()
    settings.update({
        "equipment_cost": 12000.0,
        "payback_floor_hours_month": 50.0,
        "payback_min_rate": 5.0,
        "payback_max_rate": 50.0,
        "payback_rolling_days": 90,
    })
    first = get_or_create_monthly_payback_rate(db, settings, today=date(2026, 9, 1))
    db.add(Order(
        title="Late imported history",
        status="completed",
        print_minutes=500 * 60,
        completed_at=datetime(2026, 8, 20, 12, 0, 0),
        realized_payback=5000.0,
    ))
    db.commit()
    second = get_or_create_monthly_payback_rate(db, settings, today=date(2026, 9, 20))
    assert first == second


def test_equipment_paid_off_means_zero_payback_rate():
    db = make_db()
    settings = isolated_settings()
    settings.update({
        "equipment_cost": 1000.0,
        "payback_floor_hours_month": 50.0,
        "payback_min_rate": 5.0,
        "payback_max_rate": 30.0,
    })
    db.add(Order(
        title="Paid off",
        status="completed",
        print_minutes=60,
        completed_at=datetime(2026, 8, 1, 12, 0, 0),
        realized_payback=1000.0,
    ))
    db.commit()
    assert get_or_create_monthly_payback_rate(db, settings, today=date(2026, 9, 1)) == 0.0


def test_recommended_price_realizes_planned_payback_without_double_counting():
    db = make_db()
    settings = isolated_settings()
    settings.update({
        "equipment_cost": 12000.0,
        "payback_floor_hours_month": 100.0,
        "payback_min_rate": 10.0,
        "payback_max_rate": 10.0,
        "tax_rate": 0.06,
    })
    breakdown = calculate_price(
        db,
        settings,
        print_minutes=120,
        manual_minutes=0,
        packaging_cost=0,
        complexity="normal",
        platform="direct",
        target_margin=0.35,
        materials=[{"grams": 100, "price_per_g": 1.0}],
    )
    order = Order(
        title="Recommended",
        target_margin=0.35,
        final_price=breakdown.recommended_price,
        production_cost=breakdown.production_cost,
        planned_payback=breakdown.planned_payback,
        calc_snapshot_json=json.dumps(breakdown.to_dict()),
    )
    realized = compute_realized_payback(order, settings)
    assert realized == pytest.approx(breakdown.planned_payback)
