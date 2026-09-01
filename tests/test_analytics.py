import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics import CALIBRATION_MIN_SAMPLE, build_business_stats
from app.db import Base
from app.models import Order
from app.settings import DEFAULTS


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def base_settings():
    settings = dict(DEFAULTS)
    settings["equipment_cost"] = 1000.0
    settings["payback_started_at"] = "2026-08-01"
    settings["payback_months"] = 12
    settings["payback_rolling_days"] = 90
    return settings


def exact_snapshot(customer_price: float, recommended_price: float, minimum_price: float, profit: float) -> str:
    return json.dumps({
        "tax_rate": 0.06,
        "platform_percent": 0.0,
        "platform_fixed": 0.0,
        "platform_cap": 0.0,
        "base_cost": 200.0,
        "minimum_price": minimum_price,
        "recommended_price": recommended_price,
        "customer_economics": {
            "customer_price": customer_price,
            "profit_after_payback": profit,
            "recommended_gap": customer_price - recommended_price,
            "minimum_gap": customer_price - minimum_price,
            "meets_recommended_price": customer_price >= recommended_price,
            "meets_minimum_price": customer_price >= minimum_price,
        },
    })


def test_business_stats_use_completed_orders_only():
    db = make_db()
    snap = json.dumps({
        "tax_rate": 0.06,
        "platform_percent": 0.0,
        "platform_fixed": 0.0,
        "platform_cap": 0.0,
        "base_cost": 200.0,
    })
    db.add_all([
        Order(title="August", status="completed", print_minutes=600, final_price=600,
              realized_payback=120, completed_at=datetime(2026, 8, 15), calc_snapshot_json=snap),
        Order(title="September", status="completed", print_minutes=300, final_price=500,
              realized_payback=100, completed_at=datetime(2026, 9, 1), calc_snapshot_json=snap),
        Order(title="Draft", status="draft", print_minutes=1200, final_price=1000,
              realized_payback=0, calc_snapshot_json=snap),
    ])
    db.commit()
    stats = build_business_stats(db, base_settings(), today=date(2026, 9, 1))

    assert stats.completed_total == 2
    assert stats.completed_month == 1
    assert stats.revenue_month == 500
    assert stats.commercial_hours_month == 5
    assert stats.recovered_total == 220
    assert stats.equipment_remaining == 780
    assert stats.rolling_hours == 15
    assert stats.projected_months_remaining is not None
    assert stats.calibration_exact_orders == 0
    assert stats.calibration_legacy_orders == 2
    assert stats.calibration_state == "no_data"


def test_stats_have_no_forecast_without_realized_payback():
    db = make_db()
    settings = dict(DEFAULTS)
    settings["payback_started_at"] = "2026-09-01"
    stats = build_business_stats(db, settings, today=date(2026, 9, 1))
    assert stats.forecast_state == "no_data"
    assert stats.projected_months_remaining is None
    assert stats.calibration_state == "no_data"


def test_actual_price_calibration_uses_exact_snapshots_and_separates_legacy_orders():
    db = make_db()
    db.add_all([
        Order(
            title="At recommendation",
            status="completed",
            print_minutes=60,
            final_price=500,
            recommended_price=500,
            minimum_price=300,
            realized_payback=80,
            completed_at=datetime(2026, 9, 1, 10, 0),
            calc_snapshot_json=exact_snapshot(500, 500, 300, 100),
        ),
        Order(
            title="Small discount",
            status="completed",
            print_minutes=60,
            final_price=450,
            recommended_price=500,
            minimum_price=300,
            realized_payback=60,
            completed_at=datetime(2026, 9, 1, 11, 0),
            calc_snapshot_json=exact_snapshot(450, 500, 300, 70),
        ),
        Order(
            title="Below minimum",
            status="completed",
            print_minutes=60,
            final_price=250,
            recommended_price=400,
            minimum_price=300,
            realized_payback=0,
            completed_at=datetime(2026, 9, 1, 12, 0),
            calc_snapshot_json=exact_snapshot(250, 400, 300, -20),
        ),
        Order(
            title="Legacy",
            status="completed",
            print_minutes=60,
            final_price=600,
            recommended_price=600,
            minimum_price=300,
            realized_payback=50,
            completed_at=datetime(2026, 9, 1, 13, 0),
            calc_snapshot_json=json.dumps({"recommended_price": 600, "base_cost": 200}),
        ),
        Order(
            title="Deleted exact order",
            status="completed",
            print_minutes=60,
            final_price=700,
            recommended_price=500,
            minimum_price=300,
            realized_payback=100,
            completed_at=datetime(2026, 9, 1, 14, 0),
            deleted_at=datetime(2026, 9, 1, 15, 0),
            calc_snapshot_json=exact_snapshot(700, 500, 300, 200),
        ),
    ])
    db.commit()

    stats = build_business_stats(db, base_settings(), today=date(2026, 9, 1))

    assert stats.completed_total == 4
    assert stats.calibration_exact_orders == 3
    assert stats.calibration_legacy_orders == 1
    assert stats.calibration_revenue == pytest.approx(1200.0)
    assert stats.calibration_below_recommended == 2
    assert stats.calibration_below_minimum == 1
    assert stats.calibration_average_deviation_uah == pytest.approx(-200.0 / 3.0)
    assert stats.calibration_average_deviation_percent == pytest.approx((-0.10 - 0.375) / 3.0)
    assert stats.calibration_profit_after_payback == pytest.approx(150.0)
    assert stats.calibration_average_profit_after_payback == pytest.approx(50.0)
    assert stats.calibration_margin_after_payback == pytest.approx(150.0 / 1200.0)
    assert stats.calibration_realized_payback == pytest.approx(140.0)
    assert stats.calibration_min_sample == CALIBRATION_MIN_SAMPLE
    assert stats.calibration_state == "small_sample"


def test_calibration_is_immune_to_later_global_setting_changes():
    db = make_db()
    db.add(Order(
        title="Stable snapshot",
        status="completed",
        print_minutes=60,
        final_price=450,
        recommended_price=500,
        minimum_price=300,
        realized_payback=60,
        completed_at=datetime(2026, 9, 1, 11, 0),
        calc_snapshot_json=exact_snapshot(450, 500, 300, 70),
    ))
    db.commit()

    before_settings = base_settings()
    before = build_business_stats(db, before_settings, today=date(2026, 9, 1)).to_dict()

    after_settings = base_settings()
    after_settings.update({
        "tax_rate": 0.25,
        "target_margin": 0.75,
        "min_margin": 0.50,
        "platform_direct_percent": 0.30,
        "equipment_cost": 999999.0,
    })
    after = build_business_stats(db, after_settings, today=date(2026, 9, 1)).to_dict()

    calibration_keys = [
        key for key in before
        if key.startswith("calibration_")
    ]
    assert calibration_keys
    for key in calibration_keys:
        assert after[key] == before[key], key


def test_stale_customer_economics_snapshot_is_not_treated_as_exact():
    db = make_db()
    db.add(Order(
        title="Stale",
        status="completed",
        print_minutes=60,
        final_price=400,
        recommended_price=500,
        minimum_price=300,
        realized_payback=60,
        completed_at=datetime(2026, 9, 1, 11, 0),
        calc_snapshot_json=exact_snapshot(450, 500, 300, 70),
    ))
    db.commit()

    stats = build_business_stats(db, base_settings(), today=date(2026, 9, 1))
    assert stats.calibration_exact_orders == 0
    assert stats.calibration_legacy_orders == 1
