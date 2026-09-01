import json
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics import build_business_stats
from app.db import Base
from app.models import Order
from app.settings import DEFAULTS


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


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
    settings = dict(DEFAULTS)
    settings["equipment_cost"] = 1000.0
    settings["payback_started_at"] = "2026-08-01"
    settings["payback_months"] = 12
    settings["payback_rolling_days"] = 90
    stats = build_business_stats(db, settings, today=date(2026, 9, 1))

    assert stats.completed_total == 2
    assert stats.completed_month == 1
    assert stats.revenue_month == 500
    assert stats.commercial_hours_month == 5
    assert stats.recovered_total == 220
    assert stats.equipment_remaining == 780
    assert stats.rolling_hours == 15
    assert stats.projected_months_remaining is not None


def test_stats_have_no_forecast_without_realized_payback():
    db = make_db()
    settings = dict(DEFAULTS)
    settings["payback_started_at"] = "2026-09-01"
    stats = build_business_stats(db, settings, today=date(2026, 9, 1))
    assert stats.forecast_state == "no_data"
    assert stats.projected_months_remaining is None
