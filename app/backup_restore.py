from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from . import __version__
from .db import DATA_DIR
from .models import Filament, MonthlyPaybackRate, Order, OrderMaterial, Setting
from .settings import DEFAULTS

BACKUP_SCHEMA = "3d-print-cost-backup-v1"
MAX_BACKUP_BYTES = 25 * 1024 * 1024
CONFIRM_PREFIX = "RESTORE-"
STATUSES = {"draft", "quoted", "accepted", "printing", "completed", "cancelled"}
COMPLEXITIES = {"simple", "normal", "complex", "very_complex"}
PLATFORMS = {"direct", "olx_private", "olx_business"}
MATERIAL_SOURCES = {"local", "manual", "spoolman"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class BackupValidationError(ValueError):
    pass


@dataclass
class RestorePlan:
    fingerprint: str
    confirmation_token: str
    data: dict[str, Any]
    warnings: list[str]
    ignored_settings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BACKUP_SCHEMA,
            "fingerprint": self.fingerprint,
            "confirmation_token": self.confirmation_token,
            "counts": {
                "settings": len(self.data["settings"]),
                "filaments": len(self.data["filaments"]),
                "orders": len(self.data["orders"]),
                "order_materials": sum(len(o["materials"]) for o in self.data["orders"]),
                "monthly_payback_rates": len(self.data["monthly_payback_rates"]),
            },
            "warnings": self.warnings,
            "ignored_settings": self.ignored_settings,
        }


def _need_object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise BackupValidationError(f"{label}: ожидался JSON-объект.")
    return value


def _need_list(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise BackupValidationError(f"{label}: ожидался JSON-массив.")
    return value


def _string(value: Any, label: str, *, max_len: int, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise BackupValidationError(f"{label}: ожидалась строка.")
    value = value.strip() if not allow_empty else value
    if not allow_empty and not value:
        raise BackupValidationError(f"{label}: значение не может быть пустым.")
    if len(value) > max_len:
        raise BackupValidationError(f"{label}: строка слишком длинная (>{max_len}).")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BackupValidationError(f"{label}: ожидалось число.")
    value = float(value)
    if not math.isfinite(value):
        raise BackupValidationError(f"{label}: число должно быть конечным.")
    if minimum is not None and value < minimum:
        raise BackupValidationError(f"{label}: значение меньше допустимого {minimum}.")
    if maximum is not None and value > maximum:
        raise BackupValidationError(f"{label}: значение больше допустимого {maximum}.")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    number = _number(value, label, minimum=minimum)
    if not number.is_integer():
        raise BackupValidationError(f"{label}: ожидалось целое число.")
    return int(number)


def _optional_number(value: Any, label: str, *, minimum: float | None = None) -> float | None:
    if value is None:
        return None
    return _number(value, label, minimum=minimum)


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise BackupValidationError(f"{label}: ожидалось true/false.")
    return value


def _datetime(value: Any, label: str, *, optional: bool = True) -> datetime | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise BackupValidationError(f"{label}: ожидалась ISO-дата/время.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise BackupValidationError(f"{label}: некорректная ISO-дата/время.") from exc


def _setting_value(key: str, value: Any) -> Any:
    default = DEFAULTS[key]
    label = f"settings.{key}"
    if isinstance(default, bool):
        return _bool(value, label)
    if isinstance(default, int) and not isinstance(default, bool):
        return _integer(value, label, minimum=0)
    if isinstance(default, float):
        return _number(value, label)
    if isinstance(default, str):
        return _string(value, label, max_len=2048)
    raise BackupValidationError(f"{label}: неподдерживаемый тип настройки.")


def validate_backup(raw: bytes) -> RestorePlan:
    if len(raw) > MAX_BACKUP_BYTES:
        raise BackupValidationError("Backup больше 25 MiB; восстановление остановлено для безопасности.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise BackupValidationError("Backup должен быть UTF-8 JSON.") from exc
    except json.JSONDecodeError as exc:
        raise BackupValidationError(f"Некорректный JSON: {exc.msg}.") from exc

    root = _need_object(payload, "backup")
    if root.get("schema") != BACKUP_SCHEMA:
        raise BackupValidationError(
            f"Неподдерживаемая схема backup: {root.get('schema')!r}. Ожидалась {BACKUP_SCHEMA}."
        )

    warnings: list[str] = []
    source_settings = _need_object(root.get("settings", {}), "settings")
    ignored_settings = sorted(k for k in source_settings if k not in DEFAULTS)
    if ignored_settings:
        warnings.append("Неизвестные настройки будут проигнорированы: " + ", ".join(ignored_settings))
    missing_settings = sorted(k for k in DEFAULTS if k not in source_settings)
    if missing_settings:
        warnings.append(
            f"В backup отсутствуют {len(missing_settings)} текущих настроек; для них будут использованы значения по умолчанию."
        )
    settings = {
        key: _setting_value(key, source_settings[key]) if key in source_settings else default
        for key, default in DEFAULTS.items()
    }

    filaments: list[dict[str, Any]] = []
    filament_ids: set[int] = set()
    for index, raw_f in enumerate(_need_list(root.get("filaments", []), "filaments")):
        f = _need_object(raw_f, f"filaments[{index}]")
        fid = _integer(f.get("id"), f"filaments[{index}].id", minimum=1)
        if fid in filament_ids:
            raise BackupValidationError(f"Повторяющийся filament id: {fid}.")
        filament_ids.add(fid)
        filaments.append({
            "id": fid,
            "name": _string(f.get("name", ""), f"filaments[{index}].name", max_len=160, allow_empty=False),
            "brand": _string(f.get("brand", ""), f"filaments[{index}].brand", max_len=100),
            "material": _string(f.get("material", ""), f"filaments[{index}].material", max_len=60),
            "color": _string(f.get("color", ""), f"filaments[{index}].color", max_len=80),
            "weight_g": _number(f.get("weight_g"), f"filaments[{index}].weight_g", minimum=0.001),
            "purchase_price": _number(f.get("purchase_price"), f"filaments[{index}].purchase_price", minimum=0),
            "archived": _bool(f.get("archived", False), f"filaments[{index}].archived"),
            "created_at": _datetime(f.get("created_at"), f"filaments[{index}].created_at") or datetime.utcnow(),
        })

    orders: list[dict[str, Any]] = []
    order_ids: set[int] = set()
    for index, raw_o in enumerate(_need_list(root.get("orders", []), "orders")):
        o = _need_object(raw_o, f"orders[{index}]")
        oid = _integer(o.get("id"), f"orders[{index}].id", minimum=1)
        if oid in order_ids:
            raise BackupValidationError(f"Повторяющийся order id: {oid}.")
        order_ids.add(oid)
        status = _string(o.get("status", "draft"), f"orders[{index}].status", max_len=32)
        complexity = _string(o.get("complexity", "normal"), f"orders[{index}].complexity", max_len=32)
        platform = _string(o.get("platform", "direct"), f"orders[{index}].platform", max_len=32)
        if status not in STATUSES:
            raise BackupValidationError(f"orders[{index}].status: неизвестное значение {status!r}.")
        if complexity not in COMPLEXITIES:
            raise BackupValidationError(f"orders[{index}].complexity: неизвестное значение {complexity!r}.")
        if platform not in PLATFORMS:
            raise BackupValidationError(f"orders[{index}].platform: неизвестное значение {platform!r}.")
        calc_snapshot = _string(o.get("calc_snapshot_json", "{}"), f"orders[{index}].calc_snapshot_json", max_len=2_000_000)

        materials: list[dict[str, Any]] = []
        for m_index, raw_m in enumerate(_need_list(o.get("materials", []), f"orders[{index}].materials")):
            m = _need_object(raw_m, f"orders[{index}].materials[{m_index}]")
            filament_id = m.get("filament_id")
            if filament_id is not None:
                filament_id = _integer(filament_id, f"orders[{index}].materials[{m_index}].filament_id", minimum=1)
                if filament_id not in filament_ids:
                    raise BackupValidationError(
                        f"orders[{index}].materials[{m_index}]: filament_id {filament_id} отсутствует в backup."
                    )
            source = _string(m.get("source", "manual"), f"orders[{index}].materials[{m_index}].source", max_len=32)
            if source not in MATERIAL_SOURCES:
                raise BackupValidationError(f"orders[{index}].materials[{m_index}].source: неизвестное значение {source!r}.")
            materials.append({
                "filament_id": filament_id,
                "source": source,
                "source_ref": _string(m.get("source_ref", ""), f"orders[{index}].materials[{m_index}].source_ref", max_len=120),
                "name_snapshot": _string(m.get("name_snapshot", ""), f"orders[{index}].materials[{m_index}].name_snapshot", max_len=180, allow_empty=False),
                "material_snapshot": _string(m.get("material_snapshot", ""), f"orders[{index}].materials[{m_index}].material_snapshot", max_len=60),
                "grams": _number(m.get("grams", 0), f"orders[{index}].materials[{m_index}].grams", minimum=0),
                "price_per_g_snapshot": _number(m.get("price_per_g_snapshot", 0), f"orders[{index}].materials[{m_index}].price_per_g_snapshot", minimum=0),
                "remaining_g_snapshot": _optional_number(m.get("remaining_g_snapshot"), f"orders[{index}].materials[{m_index}].remaining_g_snapshot", minimum=0),
            })

        orders.append({
            "id": oid,
            "title": _string(o.get("title", ""), f"orders[{index}].title", max_len=180, allow_empty=False),
            "client": _string(o.get("client", ""), f"orders[{index}].client", max_len=180),
            "status": status,
            "print_minutes": _integer(o.get("print_minutes", 0), f"orders[{index}].print_minutes", minimum=0),
            "manual_minutes": _integer(o.get("manual_minutes", 0), f"orders[{index}].manual_minutes", minimum=0),
            "packaging_cost": _number(o.get("packaging_cost", 0), f"orders[{index}].packaging_cost", minimum=0),
            "complexity": complexity,
            "platform": platform,
            "electricity_kwh": _optional_number(o.get("electricity_kwh"), f"orders[{index}].electricity_kwh", minimum=0),
            "target_margin": _number(o.get("target_margin", 0.35), f"orders[{index}].target_margin", minimum=0, maximum=1),
            "final_price": _optional_number(o.get("final_price"), f"orders[{index}].final_price", minimum=0),
            "production_cost": _number(o.get("production_cost", 0), f"orders[{index}].production_cost", minimum=0),
            "minimum_price": _number(o.get("minimum_price", 0), f"orders[{index}].minimum_price", minimum=0),
            "recommended_price": _number(o.get("recommended_price", 0), f"orders[{index}].recommended_price", minimum=0),
            "planned_payback": _number(o.get("planned_payback", 0), f"orders[{index}].planned_payback", minimum=0),
            "realized_payback": _number(o.get("realized_payback", 0), f"orders[{index}].realized_payback", minimum=0),
            "expected_profit": _number(o.get("expected_profit", 0), f"orders[{index}].expected_profit"),
            "payback_rate_snapshot": _number(o.get("payback_rate_snapshot", 0), f"orders[{index}].payback_rate_snapshot", minimum=0),
            "calc_snapshot_json": calc_snapshot,
            "archived": _bool(o.get("archived", False), f"orders[{index}].archived"),
            "deleted_at": _datetime(o.get("deleted_at"), f"orders[{index}].deleted_at"),
            "created_at": _datetime(o.get("created_at"), f"orders[{index}].created_at") or datetime.utcnow(),
            "updated_at": _datetime(o.get("updated_at"), f"orders[{index}].updated_at") or datetime.utcnow(),
            "completed_at": _datetime(o.get("completed_at"), f"orders[{index}].completed_at"),
            "materials": materials,
        })

    rates: list[dict[str, Any]] = []
    months: set[str] = set()
    for index, raw_r in enumerate(_need_list(root.get("monthly_payback_rates", []), "monthly_payback_rates")):
        r = _need_object(raw_r, f"monthly_payback_rates[{index}]")
        month = _string(r.get("month", ""), f"monthly_payback_rates[{index}].month", max_len=7, allow_empty=False)
        if not MONTH_RE.match(month):
            raise BackupValidationError(f"monthly_payback_rates[{index}].month: ожидался YYYY-MM.")
        if month in months:
            raise BackupValidationError(f"Повторяющийся месяц окупаемости: {month}.")
        months.add(month)
        rates.append({
            "month": month,
            "rate": _number(r.get("rate", 0), f"monthly_payback_rates[{index}].rate", minimum=0),
            "reference_hours": _number(r.get("reference_hours", 0), f"monthly_payback_rates[{index}].reference_hours", minimum=0),
            "remaining_equipment": _number(r.get("remaining_equipment", 0), f"monthly_payback_rates[{index}].remaining_equipment", minimum=0),
            "recovered_before": _number(r.get("recovered_before", 0), f"monthly_payback_rates[{index}].recovered_before", minimum=0),
            "created_at": _datetime(r.get("created_at"), f"monthly_payback_rates[{index}].created_at") or datetime.utcnow(),
        })

    fingerprint = hashlib.sha256(raw).hexdigest()
    return RestorePlan(
        fingerprint=fingerprint,
        confirmation_token=CONFIRM_PREFIX + fingerprint[:16].upper(),
        data={
            "settings": settings,
            "filaments": filaments,
            "orders": orders,
            "monthly_payback_rates": rates,
        },
        warnings=warnings,
        ignored_settings=ignored_settings,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_current_backup(db: Session) -> dict[str, Any]:
    settings = dict(DEFAULTS)
    for row in db.query(Setting).all():
        try:
            settings[row.key] = json.loads(row.value)
        except Exception:
            settings[row.key] = row.value
    filaments = db.query(Filament).order_by(Filament.id).all()
    orders = db.query(Order).order_by(Order.id).all()
    rates = db.query(MonthlyPaybackRate).order_by(MonthlyPaybackRate.month).all()
    return {
        "schema": BACKUP_SCHEMA,
        "app_version": __version__,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "settings": settings,
        "filaments": [
            {"id": f.id, "name": f.name, "brand": f.brand, "material": f.material, "color": f.color,
             "weight_g": f.weight_g, "purchase_price": f.purchase_price, "archived": f.archived,
             "created_at": _iso(f.created_at)} for f in filaments
        ],
        "orders": [
            {"id": o.id, "title": o.title, "client": o.client, "status": o.status,
             "print_minutes": o.print_minutes, "manual_minutes": o.manual_minutes,
             "packaging_cost": o.packaging_cost, "complexity": o.complexity, "platform": o.platform,
             "electricity_kwh": o.electricity_kwh, "target_margin": o.target_margin,
             "final_price": o.final_price, "production_cost": o.production_cost,
             "minimum_price": o.minimum_price, "recommended_price": o.recommended_price,
             "planned_payback": o.planned_payback, "realized_payback": o.realized_payback,
             "expected_profit": o.expected_profit, "payback_rate_snapshot": o.payback_rate_snapshot,
             "calc_snapshot_json": o.calc_snapshot_json, "archived": o.archived,
             "deleted_at": _iso(o.deleted_at), "created_at": _iso(o.created_at),
             "updated_at": _iso(o.updated_at), "completed_at": _iso(o.completed_at),
             "materials": [
                 {"filament_id": m.filament_id, "source": m.source, "source_ref": m.source_ref,
                  "name_snapshot": m.name_snapshot, "material_snapshot": m.material_snapshot,
                  "grams": m.grams, "price_per_g_snapshot": m.price_per_g_snapshot,
                  "remaining_g_snapshot": m.remaining_g_snapshot} for m in o.materials
             ]} for o in orders
        ],
        "monthly_payback_rates": [
            {"month": r.month, "rate": r.rate, "reference_hours": r.reference_hours,
             "remaining_equipment": r.remaining_equipment, "recovered_before": r.recovered_before,
             "created_at": _iso(r.created_at)} for r in rates
        ],
    }


def create_safety_backup(db: Session, safety_dir: Path | None = None) -> Path:
    directory = safety_dir or (DATA_DIR / "restore-safety")
    directory.mkdir(parents=True, exist_ok=True)
    payload = serialize_current_backup(db)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"before-restore-{stamp}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def apply_restore(
    db: Session,
    plan: RestorePlan,
    confirmation_token: str,
    *,
    safety_dir: Path | None = None,
) -> dict[str, Any]:
    if confirmation_token != plan.confirmation_token:
        raise BackupValidationError("Confirmation token не совпадает с предварительно проверенным backup.")

    safety_path = create_safety_backup(db, safety_dir=safety_dir)
    # Reads used for the safety snapshot may have opened an implicit transaction.
    # Close it before the all-or-nothing replacement transaction begins.
    db.commit()
    try:
        with db.begin():
            db.query(OrderMaterial).delete(synchronize_session=False)
            db.query(Order).delete(synchronize_session=False)
            db.query(MonthlyPaybackRate).delete(synchronize_session=False)
            db.query(Filament).delete(synchronize_session=False)
            db.query(Setting).delete(synchronize_session=False)

            for key, value in plan.data["settings"].items():
                db.add(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))

            for f in plan.data["filaments"]:
                db.add(Filament(**f))
            db.flush()

            for source in plan.data["orders"]:
                fields = {k: v for k, v in source.items() if k != "materials"}
                order = Order(**fields)
                db.add(order)
                db.flush()
                for material in source["materials"]:
                    db.add(OrderMaterial(order_id=order.id, **material))

            for rate in plan.data["monthly_payback_rates"]:
                db.add(MonthlyPaybackRate(**rate))
            db.flush()
    except Exception:
        db.rollback()
        raise

    result = plan.to_dict()
    result.update({
        "restored": True,
        "safety_backup": safety_path.name,
    })
    return result
