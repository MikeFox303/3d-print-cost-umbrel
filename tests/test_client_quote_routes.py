import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import Order, OrderMaterial
from app.server import app


FORBIDDEN_KEYS = {
    "production_cost",
    "minimum_price",
    "recommended_price",
    "planned_payback",
    "expected_profit",
    "tax_rate",
    "target_margin",
    "platform_fee",
    "risk_rate",
}


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


def form(final_price="450"):
    return {
        "title": "Крепление камеры",
        "print_hours": "2",
        "print_mins": "15",
        "manual_minutes": "0",
        "packaging_cost": "0",
        "complexity": "normal",
        "platform": "direct",
        "target_margin": "35",
        "final_price": final_price,
        "filament_id": "",
        "grams": "100",
        "manual_name": "PETG Black",
        "manual_material": "PETG",
        "manual_price_per_g": "1.0",
        "material_source": "manual",
        "material_source_ref": "",
        "remaining_g": "",
    }


def assert_client_safe_payload(payload):
    assert FORBIDDEN_KEYS.isdisjoint(payload.keys())
    raw = json.dumps(payload, ensure_ascii=False).casefold()
    for term in ("себесто", "марж", "налог", "комис", "окуп", "риск"):
        assert term not in raw


def test_preview_client_message_uses_manual_customer_price():
    db = make_db()
    override(db)
    try:
        response = TestClient(app).post("/api/quotes/client-message", data=form())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "quote_preview"
    assert payload["customer_price"] == 450.0
    assert payload["print_minutes"] == 135
    assert "Стоимость: 450 грн" in payload["text"]
    assert "PETG Black" in payload["text"]
    assert_client_safe_payload(payload)


def test_preview_client_message_uses_rounded_recommended_when_price_is_blank():
    db = make_db()
    override(db)
    try:
        response = TestClient(app).post("/api/quotes/client-message", data=form(final_price=""))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["customer_price"] > 0
    assert payload["customer_price"] % 10 == 0
    assert f"Стоимость: {int(payload['customer_price'])} грн" in payload["text"]
    assert_client_safe_payload(payload)


def test_saved_order_client_message_uses_snapshotted_material_names_and_final_price():
    db = make_db()
    order = Order(
        id=91,
        title="Корпус датчика",
        status="quoted",
        print_minutes=95,
        final_price=525.0,
        target_margin=0.35,
        calc_snapshot_json="{}",
    )
    db.add(order)
    db.flush()
    db.add(OrderMaterial(
        order_id=order.id,
        source="manual",
        source_ref="",
        name_snapshot="PETG Orange",
        material_snapshot="PETG",
        grams=80,
        price_per_g_snapshot=0.8,
    ))
    db.commit()

    override(db)
    try:
        response = TestClient(app).get("/api/orders/91/client-message")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "saved_order"
    assert payload["order_id"] == 91
    assert payload["customer_price"] == 525.0
    assert "Корпус датчика" in payload["text"]
    assert "PETG Orange" in payload["text"]
    assert_client_safe_payload(payload)
