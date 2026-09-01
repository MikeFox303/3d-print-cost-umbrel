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

    estimated_kwh = (
        float(order.electricity_kwh)
        if order.electricity_kwh is not None
        else (order.print_minutes / 60.0) * float(settings.get("average_power_w", 0)) / 1000.0
    )
    actual_kwh = float(measured["kwh"])
    tariff = float(settings.get("electricity_tariff", 0))
    return {
        **measured,
        "order_id": order.id,
        "window_source": "completed_at - print_minutes",
        "estimated_kwh": estimated_kwh,
        "difference_kwh": actual_kwh - estimated_kwh,
        "actual_cost": actual_kwh * tariff,
        "tariff": tariff,
        "persisted": False,
    }
