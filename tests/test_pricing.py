from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.pricing import calculate_price
from app.settings import DEFAULTS


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def settings():
    s = dict(DEFAULTS)
    s["payback_started_at"] = date.today().isoformat()
    return s


def test_reference_petg_order_has_two_prices():
    db = make_db()
    b = calculate_price(db, settings(), print_minutes=300, manual_minutes=15, packaging_cost=20,
        complexity="normal", platform="direct", target_margin=0.35,
        materials=[{"grams":100,"price_per_g":0.619}], electricity_kwh=None)
    assert b.production_cost > 130
    assert b.minimum_price == 300
    assert b.recommended_price > b.minimum_price
    assert 15 <= b.payback_rate <= 30


def test_explicit_energy_overrides_average_power_and_is_snapshotted():
    db = make_db()
    s = settings()
    s["electricity_tariff"] = 4.32
    s["average_power_w"] = 999.0
    b = calculate_price(db, s, print_minutes=600, manual_minutes=0, packaging_cost=0,
        complexity="simple", platform="direct", target_margin=0.35,
        materials=[], electricity_kwh=1.0)
    assert round(b.electricity, 2) == 4.32
    assert b.electricity_kwh_used == 1.0
    assert b.electricity_tariff == 4.32
    assert b.electricity_source == "explicit_kwh"
    snap = b.to_dict()
    assert snap["electricity_kwh_used"] == 1.0
    assert snap["electricity_tariff"] == 4.32
    assert snap["electricity_source"] == "explicit_kwh"


def test_average_power_energy_basis_is_snapshotted():
    db = make_db()
    s = settings()
    s["electricity_tariff"] = 4.32
    s["average_power_w"] = 180.0
    b = calculate_price(db, s, print_minutes=120, manual_minutes=0, packaging_cost=0,
        complexity="simple", platform="direct", target_margin=0.35,
        materials=[], electricity_kwh=None)
    assert b.electricity_kwh_used == 0.36
    assert b.electricity == 0.36 * 4.32
    assert b.electricity_source == "average_power"


def test_low_load_is_capped_for_customer_fairness():
    db = make_db()
    s = settings(); s["payback_floor_hours_month"] = 120.0; s["payback_max_rate"] = 30.0
    b = calculate_price(db, s, print_minutes=60, manual_minutes=0, packaging_cost=0,
        complexity="simple", platform="direct", target_margin=0.35,
        materials=[], electricity_kwh=None)
    assert b.payback_rate == 30.0
