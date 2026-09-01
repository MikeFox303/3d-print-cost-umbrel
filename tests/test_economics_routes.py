import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import Order
from app.pricing import calculate_price, evaluate_customer_price
from app.server import app
from app.settings import get_settings


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


def manual_order_form(final_price: str = "200"):
    return {
        "title": "Discounted quote",
        "print_hours": "1",
        "print_mins": "0",
        "manual_minutes": "0",
        "packaging_cost": "0",
        "complexity": "normal",
        "platform": "direct",
        "target_margin": "35",
        "final_price": final_price,
        "filament_id": "",
        "grams": "100",
        "manual_name": "PETG",
        "manual_material": "PETG",
        "manual_price_per_g": "1.0",
        "material_source": "manual",
        "material_source_ref": "",
        "remaining_g": "",
    }


def test_quote_economics_preview_uses_manual_customer_price():
    db = make_db()
    override(db)
    try:
        response = TestClient(app).post(
            "/api/quotes/economics-preview",
            data=manual_order_form(),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["customer_price_source"] == "manual"
    assert payload["customer_economics"]["customer_price"] == 200.0
    assert payload["customer_economics"]["meets_minimum_price"] is False
    assert any("ниже минимальной" in warning for warning in payload["warnings"])


def test_saving_manual_price_snapshots_its_profit_and_payback():
    db = make_db()
    override(db)
    try:
        response = TestClient(app).post(
            "/orders",
            data=manual_order_form(),
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 303
    order = db.query(Order).one()
    snapshot = json.loads(order.calc_snapshot_json)
    customer = snapshot["customer_economics"]

    assert order.final_price == 200.0
    assert customer["customer_price"] == 200.0
    assert order.expected_profit == pytest.approx(customer["profit_after_payback"])
    assert customer["payback_contribution"] == 0.0
    assert snapshot["extra_profit_payback_share"] == get_settings(db)["extra_profit_payback_share"]
    assert order.expected_profit != pytest.approx(snapshot["expected_profit"])


def test_saved_order_economics_reads_historical_snapshot():
    db = make_db()
    settings = get_settings(db)
    breakdown = calculate_price(
        db,
        settings,
        print_minutes=120,
        manual_minutes=10,
        packaging_cost=20,
        complexity="normal",
        platform="direct",
        target_margin=0.35,
        materials=[{"grams": 100, "price_per_g": 0.8}],
    )
    customer_price = breakdown.recommended_price + 100
    expected = evaluate_customer_price(breakdown, customer_price)
    order = Order(
        id=77,
        title="Saved economics",
        status="quoted",
        print_minutes=120,
        target_margin=0.35,
        final_price=customer_price,
        production_cost=breakdown.production_cost,
        minimum_price=breakdown.minimum_price,
        recommended_price=breakdown.recommended_price,
        planned_payback=breakdown.planned_payback,
        payback_rate_snapshot=breakdown.payback_rate,
        expected_profit=breakdown.expected_profit,
        calc_snapshot_json=json.dumps(breakdown.to_dict()),
    )
    db.add(order)
    db.commit()

    override(db)
    try:
        response = TestClient(app).get("/api/orders/77/customer-economics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    actual = payload["customer_economics"]
    assert payload["source"] == "saved_financial_snapshot"
    assert payload["snapshot_has_v013_share"] is True
    assert actual["customer_price"] == customer_price
    assert actual["payback_contribution"] == expected.payback_contribution
    assert actual["profit_after_payback"] == expected.profit_after_payback
