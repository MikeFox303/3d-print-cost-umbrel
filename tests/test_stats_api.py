import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import Order
from app.server import app


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_stats_api_exposes_exact_actual_price_calibration_fields():
    db = make_db()
    snapshot = {
        "tax_rate": 0.06,
        "platform_percent": 0.0,
        "platform_fixed": 0.0,
        "platform_cap": 0.0,
        "base_cost": 200.0,
        "minimum_price": 300.0,
        "recommended_price": 500.0,
        "customer_economics": {
            "customer_price": 450.0,
            "profit_after_payback": 70.0,
            "recommended_gap": -50.0,
            "minimum_gap": 150.0,
            "meets_recommended_price": False,
            "meets_minimum_price": True,
        },
    }
    db.add(Order(
        title="API calibration",
        status="completed",
        print_minutes=60,
        final_price=450.0,
        recommended_price=500.0,
        minimum_price=300.0,
        realized_payback=60.0,
        completed_at=datetime(2026, 9, 1, 12, 0),
        calc_snapshot_json=json.dumps(snapshot),
    ))
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/stats")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["calibration_exact_orders"] == 1
    assert payload["calibration_legacy_orders"] == 0
    assert payload["calibration_below_recommended"] == 1
    assert payload["calibration_below_minimum"] == 0
    assert payload["calibration_average_deviation_uah"] == -50.0
    assert payload["calibration_average_deviation_percent"] == -0.1
    assert payload["calibration_profit_after_payback"] == 70.0
    assert payload["calibration_margin_after_payback"] == 70.0 / 450.0
    assert payload["calibration_realized_payback"] == 60.0
    assert payload["calibration_state"] == "small_sample"
