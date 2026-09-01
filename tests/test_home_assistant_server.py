import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.integrations import ReadOnlyHomeAssistantClient
from app.models import Order
from app.pricing import calculate_price, evaluate_customer_price
from app.server import app
from app.settings import get_settings, set_setting


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def override(db):
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db


def fake_measurement(kwh: float):
    async def fake_measure(self, entity_id, start, end):
        return {
            "entity_id": entity_id,
            "sensor_unit": "W",
            "mode": "power_integral",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "samples": 10,
            "kwh": kwh,
        }
    return fake_measure


def test_home_assistant_routes_are_registered():
    routes = [
        (getattr(route, "path", None), set(getattr(route, "methods", set()) or set()))
        for route in app.routes
    ]
    assert any(path == "/home-assistant" and "GET" in methods for path, methods in routes)
    assert any(
        path == "/api/orders/{order_id}/home-assistant-energy" and "GET" in methods
        for path, methods in routes
    )


def test_legacy_home_assistant_energy_is_read_only_and_marks_fallback(monkeypatch):
    db = make_db()
    order = Order(
        id=42,
        title="Energy test",
        status="completed",
        print_minutes=60,
        completed_at=datetime(2026, 9, 1, 12, 0, 0),
        electricity_kwh=None,
        expected_profit=100.0,
        calc_snapshot_json='{"electricity": 0.78}',
    )
    db.add(order)
    db.commit()
    set_setting(db, "home_assistant_enabled", True)
    set_setting(db, "home_assistant_url", "http://ha.local:8123")
    set_setting(db, "home_assistant_energy_entity", "sensor.x2d_power")
    set_setting(db, "average_power_w", 180.0)
    set_setting(db, "electricity_tariff", 4.32)

    monkeypatch.setattr(ReadOnlyHomeAssistantClient, "measure_energy", fake_measurement(0.24))
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")

    override(db)
    try:
        response = TestClient(app).get("/api/orders/42/home-assistant-energy")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["kwh"] == 0.24
    assert payload["actual_kwh"] == 0.24
    assert round(payload["estimated_kwh"], 3) == 0.18
    assert round(payload["quoted_kwh"], 3) == 0.18
    assert payload["quoted_electricity_cost"] == pytest.approx(0.78)
    assert payload["actual_cost"] == pytest.approx(0.24 * 4.32)
    assert payload["electricity_cost_delta"] == pytest.approx(0.24 * 4.32 - 0.78)
    assert payload["historical_exact"] is False
    assert payload["tariff_source"] == "current_settings_fallback"
    assert payload["compatibility_warning"]
    assert payload["reconciliation_scope"] == "electricity_only"
    assert payload["quote_snapshot_unchanged"] is True
    assert payload["persisted"] is False

    db.expire_all()
    untouched = db.get(Order, 42)
    assert untouched.electricity_kwh is None
    assert untouched.calc_snapshot_json == '{"electricity": 0.78}'


def test_new_order_reconciliation_uses_quote_time_tariff_after_global_change(monkeypatch):
    db = make_db()
    set_setting(db, "home_assistant_enabled", True)
    set_setting(db, "home_assistant_url", "http://ha.local:8123")
    set_setting(db, "home_assistant_energy_entity", "sensor.x2d_power")
    set_setting(db, "electricity_tariff", 4.32)
    set_setting(db, "average_power_w", 180.0)

    settings = get_settings(db)
    breakdown = calculate_price(
        db,
        settings,
        print_minutes=60,
        manual_minutes=0,
        packaging_cost=0,
        complexity="normal",
        platform="direct",
        target_margin=0.35,
        materials=[{"grams": 100, "price_per_g": 0.8}],
        electricity_kwh=0.20,
    )
    customer_price = 500.0
    economics = evaluate_customer_price(breakdown, customer_price)
    snapshot = breakdown.to_dict()
    snapshot["customer_economics"] = economics.to_dict()
    order = Order(
        id=43,
        title="Snapshotted energy",
        status="completed",
        print_minutes=60,
        completed_at=datetime(2026, 9, 1, 12, 0, 0),
        electricity_kwh=0.20,
        target_margin=0.35,
        final_price=customer_price,
        production_cost=breakdown.production_cost,
        minimum_price=breakdown.minimum_price,
        recommended_price=breakdown.recommended_price,
        planned_payback=breakdown.planned_payback,
        expected_profit=economics.profit_after_payback,
        payback_rate_snapshot=breakdown.payback_rate,
        calc_snapshot_json=json.dumps(snapshot),
    )
    db.add(order)
    db.commit()

    # A later tariff/power change must not rewrite the economics of this quote.
    set_setting(db, "electricity_tariff", 9.99)
    set_setting(db, "average_power_w", 999.0)

    monkeypatch.setattr(ReadOnlyHomeAssistantClient, "measure_energy", fake_measurement(0.25))
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")

    override(db)
    try:
        response = TestClient(app).get("/api/orders/43/home-assistant-energy")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical_exact"] is True
    assert payload["tariff"] == pytest.approx(4.32)
    assert payload["tariff_source"] == "quote_snapshot"
    assert payload["quote_energy_source"] == "explicit_kwh"
    assert payload["quoted_kwh"] == pytest.approx(0.20)
    assert payload["quoted_electricity_cost"] == pytest.approx(0.20 * 4.32)
    assert payload["actual_kwh"] == pytest.approx(0.25)
    assert payload["actual_cost"] == pytest.approx(0.25 * 4.32)
    assert payload["electricity_cost_delta"] == pytest.approx(0.05 * 4.32)
    assert payload["profit_after_quoted_energy"] == pytest.approx(economics.profit_after_payback)
    assert payload["profit_after_actual_energy"] == pytest.approx(
        economics.profit_after_payback - 0.05 * 4.32
    )
    assert payload["compatibility_warning"] is None
    assert payload["persisted"] is False

    db.expire_all()
    untouched = db.get(Order, 43)
    saved_snapshot = json.loads(untouched.calc_snapshot_json)
    assert saved_snapshot["electricity_tariff"] == pytest.approx(4.32)
    assert saved_snapshot["electricity_kwh_used"] == pytest.approx(0.20)
