from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.integrations import ReadOnlyHomeAssistantClient
from app.models import Order
from app.server import app
from app.settings import set_setting


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_home_assistant_routes_are_registered():
    paths = {(getattr(route, "path", None), getattr(route, "methods", set())) for route in app.routes}
    assert any(path == "/home-assistant" and "GET" in methods for path, methods in paths)
    assert any(path == "/api/orders/{order_id}/home-assistant-energy" and "GET" in methods for path, methods in paths)


def test_home_assistant_energy_is_read_only_for_order(monkeypatch):
    db = make_db()
    order = Order(
        id=42,
        title="Energy test",
        status="completed",
        print_minutes=60,
        completed_at=datetime(2026, 9, 1, 12, 0, 0),
        electricity_kwh=None,
        calc_snapshot_json='{"electricity": 0.78}',
    )
    db.add(order)
    db.commit()
    set_setting(db, "home_assistant_enabled", True)
    set_setting(db, "home_assistant_url", "http://ha.local:8123")
    set_setting(db, "home_assistant_energy_entity", "sensor.x2d_power")
    set_setting(db, "average_power_w", 180.0)
    set_setting(db, "electricity_tariff", 4.32)

    async def fake_measure(self, entity_id, start, end):
        return {
            "entity_id": entity_id,
            "sensor_unit": "W",
            "mode": "power_integral",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "samples": 10,
            "kwh": 0.24,
        }

    monkeypatch.setattr(ReadOnlyHomeAssistantClient, "measure_energy", fake_measure)
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/orders/42/home-assistant-energy")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["kwh"] == 0.24
    assert round(payload["estimated_kwh"], 3) == 0.18
    assert round(payload["actual_cost"], 4) == round(0.24 * 4.32, 4)
    assert payload["persisted"] is False

    db.expire_all()
    untouched = db.get(Order, 42)
    assert untouched.electricity_kwh is None
    assert untouched.calc_snapshot_json == '{"electricity": 0.78}'
