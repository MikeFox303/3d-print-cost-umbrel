import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backup_restore import BackupValidationError, apply_restore, validate_backup
from app.db import Base
from app.models import Filament, Order, OrderMaterial, Setting


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def valid_backup():
    return {
        "schema": "3d-print-cost-backup-v1",
        "app_version": "0.4.0-dev.1",
        "exported_at": "2026-09-01T18:00:00Z",
        "settings": {"equipment_cost": 50000.0, "spoolman_enabled": False},
        "filaments": [
            {
                "id": 7,
                "name": "Black PETG",
                "brand": "SUNLU",
                "material": "PETG",
                "color": "Black",
                "weight_g": 1000.0,
                "purchase_price": 650.0,
                "archived": False,
                "created_at": "2026-08-01T10:00:00",
            }
        ],
        "orders": [
            {
                "id": 12,
                "title": "Camera mount",
                "client": "Test",
                "status": "completed",
                "print_minutes": 180,
                "manual_minutes": 10,
                "packaging_cost": 20.0,
                "complexity": "normal",
                "platform": "direct",
                "electricity_kwh": 0.4,
                "target_margin": 0.35,
                "final_price": 600.0,
                "production_cost": 220.0,
                "minimum_price": 420.0,
                "recommended_price": 580.0,
                "planned_payback": 50.0,
                "realized_payback": 55.0,
                "expected_profit": 120.0,
                "payback_rate_snapshot": 18.0,
                "calc_snapshot_json": "{\"base_cost\": 220}",
                "archived": False,
                "deleted_at": None,
                "created_at": "2026-08-20T10:00:00",
                "updated_at": "2026-08-20T13:00:00",
                "completed_at": "2026-08-20T13:00:00",
                "materials": [
                    {
                        "filament_id": 7,
                        "source": "local",
                        "source_ref": "7",
                        "name_snapshot": "Black PETG",
                        "material_snapshot": "PETG",
                        "grams": 120.5,
                        "price_per_g_snapshot": 0.65,
                        "remaining_g_snapshot": None,
                    }
                ],
            }
        ],
        "monthly_payback_rates": [
            {
                "month": "2026-08",
                "rate": 18.0,
                "reference_hours": 120.0,
                "remaining_equipment": 49000.0,
                "recovered_before": 1000.0,
                "created_at": "2026-08-01T00:00:00",
            }
        ],
    }


def as_bytes(data):
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def test_preview_validates_and_returns_fingerprint_and_counts():
    plan = validate_backup(as_bytes(valid_backup()))
    result = plan.to_dict()
    assert result["counts"]["orders"] == 1
    assert result["counts"]["order_materials"] == 1
    assert result["counts"]["filaments"] == 1
    assert result["confirmation_token"].startswith("RESTORE-")
    assert len(result["fingerprint"]) == 64


def test_unknown_settings_are_ignored_and_missing_settings_get_defaults():
    data = valid_backup()
    data["settings"]["future_unknown_key"] = "ignored"
    plan = validate_backup(as_bytes(data))
    assert "future_unknown_key" in plan.ignored_settings
    assert "future_unknown_key" not in plan.data["settings"]
    assert "electricity_tariff" in plan.data["settings"]
    assert plan.warnings


def test_wrong_schema_is_rejected():
    data = valid_backup(); data["schema"] = "something-else"
    with pytest.raises(BackupValidationError, match="схема"):
        validate_backup(as_bytes(data))


def test_dangling_filament_reference_is_rejected():
    data = valid_backup(); data["orders"][0]["materials"][0]["filament_id"] = 999
    with pytest.raises(BackupValidationError, match="отсутствует"):
        validate_backup(as_bytes(data))


def test_confirmation_token_is_required_before_any_mutation(tmp_path):
    db = make_db()
    db.add(Order(id=99, title="Existing", status="draft"))
    db.commit()
    plan = validate_backup(as_bytes(valid_backup()))
    with pytest.raises(BackupValidationError, match="Confirmation token"):
        apply_restore(db, plan, "WRONG", safety_dir=tmp_path)
    assert db.get(Order, 99) is not None
    assert list(tmp_path.iterdir()) == []


def test_apply_restore_replaces_database_and_creates_safety_backup(tmp_path):
    db = make_db()
    db.add(Setting(key="equipment_cost", value="123"))
    db.add(Filament(id=1, name="Old PLA", weight_g=1000, purchase_price=400))
    db.add(Order(id=99, title="Existing", status="draft", calc_snapshot_json="{}"))
    db.commit()

    plan = validate_backup(as_bytes(valid_backup()))
    result = apply_restore(db, plan, plan.confirmation_token, safety_dir=tmp_path)

    assert result["restored"] is True
    assert db.get(Order, 99) is None
    restored = db.get(Order, 12)
    assert restored is not None
    assert restored.calc_snapshot_json == "{\"base_cost\": 220}"
    assert len(restored.materials) == 1
    assert restored.materials[0].price_per_g_snapshot == 0.65
    assert db.get(Filament, 7).purchase_price == 650.0
    equipment = db.get(Setting, "equipment_cost")
    assert json.loads(equipment.value) == 50000.0

    safety_files = list(tmp_path.glob("before-restore-*.json"))
    assert len(safety_files) == 1
    safety = json.loads(safety_files[0].read_text(encoding="utf-8"))
    assert safety["orders"][0]["id"] == 99


def test_server_exposes_restore_preview_and_apply_routes():
    from app.server import app
    paths = {(getattr(route, "path", None), tuple(sorted(getattr(route, "methods", set())))) for route in app.routes}
    assert any(path == "/backup/restore" for path, _ in paths)
    assert any(path == "/api/backup/restore/preview" and "POST" in methods for path, methods in paths)
    assert any(path == "/api/backup/restore/apply" and "POST" in methods for path, methods in paths)
