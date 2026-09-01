from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import main as core
from ..db import get_db
from ..integrations import HomeAssistantReadOnlyError, ReadOnlyHomeAssistantClient
from ..secrets import (
    clear_home_assistant_token,
    get_home_assistant_token,
    save_home_assistant_token,
)
from ..settings import get_settings, set_setting

router = APIRouter()


@router.get("/home-assistant", response_class=HTMLResponse)
def home_assistant_page(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    token, token_source = get_home_assistant_token()
    return core.templates.TemplateResponse(
        request,
        "home_assistant.html",
        core.ctx(
            request,
            settings=settings,
            token_configured=bool(token),
            token_source=token_source,
        ),
    )


@router.post("/home-assistant")
async def home_assistant_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    enabled = form.get("home_assistant_enabled") == "on"
    base_url = str(form.get("home_assistant_url") or "").strip().rstrip("/")
    entity_id = str(form.get("home_assistant_energy_entity") or "").strip()
    new_token = str(form.get("home_assistant_token") or "").strip()
    clear_token = form.get("clear_home_assistant_token") == "on"

    if base_url and not base_url.startswith(("http://", "https://")):
        raise core.HTTPException(422, "Home Assistant URL должен начинаться с http:// или https://")
    if entity_id and "." not in entity_id:
        raise core.HTTPException(422, "Entity ID должен иметь вид sensor.example")

    if new_token:
        save_home_assistant_token(new_token)
    elif clear_token:
        clear_home_assistant_token()

    set_setting(db, "home_assistant_enabled", enabled)
    set_setting(db, "home_assistant_url", base_url)
    set_setting(db, "home_assistant_energy_entity", entity_id)
    return RedirectResponse("/home-assistant", status_code=303)


def _number(mapping: dict, key: str, fallback: float = 0.0) -> float:
    try:
        return float(mapping.get(key, fallback) or 0.0)
    except (TypeError, ValueError):
        return float(fallback)


def _quote_energy_basis(order, settings: dict) -> dict:
    """Return the historical quote energy basis without mutating the order.

    New v0.13 snapshots contain exact quote-time kWh/tariff fields. Older
    snapshots did not, so their kWh/tariff comparison is explicitly marked as
    a compatibility fallback instead of pretending the current settings are
    historical facts.
    """
    try:
        snapshot = json.loads(order.calc_snapshot_json or "{}")
    except json.JSONDecodeError:
        snapshot = {}

    has_exact_energy = (
        "electricity_kwh_used" in snapshot
        and "electricity_tariff" in snapshot
        and "electricity_source" in snapshot
    )
    if has_exact_energy:
        quoted_kwh = _number(snapshot, "electricity_kwh_used")
        tariff = _number(snapshot, "electricity_tariff")
        quoted_cost = _number(snapshot, "electricity", quoted_kwh * tariff)
        energy_source = str(snapshot.get("electricity_source") or "quote_snapshot")
        tariff_source = "quote_snapshot"
        historical_exact = True
        compatibility_warning = None
    else:
        tariff = float(settings.get("electricity_tariff", 0) or 0)
        if order.electricity_kwh is not None:
            quoted_kwh = float(order.electricity_kwh)
            energy_source = "legacy_order_explicit_kwh"
        else:
            quoted_kwh = (
                float(order.print_minutes or 0)
                / 60.0
                * float(settings.get("average_power_w", 0) or 0)
                / 1000.0
            )
            energy_source = "current_average_power_fallback"
        quoted_cost = _number(snapshot, "electricity", quoted_kwh * tariff)
        tariff_source = "current_settings_fallback"
        historical_exact = False
        compatibility_warning = (
            "Старый заказ не хранит тариф и расчётные кВт·ч на момент оценки; "
            "для сравнения используется текущий тариф/средняя мощность там, где исторических данных нет."
        )

    customer_economics = snapshot.get("customer_economics")
    if isinstance(customer_economics, dict) and "profit_after_payback" in customer_economics:
        quoted_profit_after_payback = _number(customer_economics, "profit_after_payback")
        profit_source = "customer_economics_snapshot"
    else:
        quoted_profit_after_payback = float(order.expected_profit or 0.0)
        profit_source = "order_expected_profit_fallback"

    return {
        "snapshot": snapshot,
        "quoted_kwh": quoted_kwh,
        "quoted_cost": quoted_cost,
        "tariff": tariff,
        "tariff_source": tariff_source,
        "quote_energy_source": energy_source,
        "historical_exact": historical_exact,
        "compatibility_warning": compatibility_warning,
        "quoted_profit_after_payback": quoted_profit_after_payback,
        "profit_source": profit_source,
    }


@router.get("/api/orders/{order_id}/home-assistant-energy")
async def order_home_assistant_energy(order_id: int, db: Session = Depends(get_db)):
    order = db.get(core.Order, order_id)
    if not order or order.deleted_at is not None:
        raise core.HTTPException(404)
    if order.status != "completed" or order.completed_at is None:
        raise core.HTTPException(409, "Фактическая энергия доступна после завершения заказа.")
    if order.print_minutes <= 0:
        raise core.HTTPException(409, "В заказе нет длительности печати.")

    settings = get_settings(db)
    if not settings.get("home_assistant_enabled"):
        raise core.HTTPException(409, "Интеграция Home Assistant выключена.")
    token, _token_source = get_home_assistant_token()
    if not token:
        raise core.HTTPException(503, "Токен Home Assistant не настроен.")

    base_url = str(settings.get("home_assistant_url") or "").strip()
    entity_id = str(settings.get("home_assistant_energy_entity") or "").strip()
    start = order.completed_at - timedelta(minutes=order.print_minutes)
    end = order.completed_at
    try:
        measured = await ReadOnlyHomeAssistantClient(base_url, token).measure_energy(entity_id, start, end)
    except HomeAssistantReadOnlyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception:
        return JSONResponse(
            {"error": "Не удалось прочитать историю Home Assistant. Проверьте URL, токен, entity_id и доступность HA."},
            status_code=502,
        )

    basis = _quote_energy_basis(order, settings)
    quoted_kwh = float(basis["quoted_kwh"])
    actual_kwh = float(measured["kwh"])
    tariff = float(basis["tariff"])
    quoted_cost = float(basis["quoted_cost"])
    actual_cost = actual_kwh * tariff
    difference_kwh = actual_kwh - quoted_kwh
    electricity_cost_delta = actual_cost - quoted_cost
    quoted_profit = float(basis["quoted_profit_after_payback"])
    profit_after_actual_energy = quoted_profit - electricity_cost_delta

    return {
        **measured,
        "order_id": order.id,
        "window_source": "completed_at - print_minutes",
        # `estimated_kwh` remains as a compatibility alias for the existing UI/API.
        "estimated_kwh": quoted_kwh,
        "quoted_kwh": quoted_kwh,
        "actual_kwh": actual_kwh,
        "difference_kwh": difference_kwh,
        "quoted_electricity_cost": quoted_cost,
        "actual_cost": actual_cost,
        "electricity_cost_delta": electricity_cost_delta,
        "tariff": tariff,
        "tariff_source": basis["tariff_source"],
        "quote_energy_source": basis["quote_energy_source"],
        "historical_exact": basis["historical_exact"],
        "compatibility_warning": basis["compatibility_warning"],
        "profit_after_quoted_energy": quoted_profit,
        "profit_after_actual_energy": profit_after_actual_energy,
        "profit_source": basis["profit_source"],
        "reconciliation_scope": "electricity_only",
        "quote_snapshot_unchanged": True,
        "persisted": False,
    }
