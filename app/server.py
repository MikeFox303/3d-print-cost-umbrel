from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy.orm import Session

from . import main as core
from .backup_restore import (
    MAX_BACKUP_BYTES,
    BackupValidationError,
    apply_restore,
    validate_backup,
)
from .db import get_db
from .integrations import HomeAssistantReadOnlyError, ReadOnlyHomeAssistantClient
from .settings import get_settings, set_setting
from .three_mf import ThreeMFImportError, import_bambu_3mf

app = core.app
BASE_DIR = Path(__file__).resolve().parent


def _validate_quote_inputs(data: dict) -> None:
    if data["print_minutes"] <= 0:
        raise core.HTTPException(422, "Укажите расчётное время печати из Bambu Studio.")
    if not data["materials"]:
        raise core.HTTPException(422, "Добавьте хотя бы один материал и его расход.")
    missing_price = [m["name"] for m in data["materials"] if float(m.get("price_per_g") or 0) <= 0]
    if missing_price:
        names = ", ".join(missing_price[:4])
        raise core.HTTPException(
            422,
            f"Не задана цена материала: {names}. Выберите катушку или укажите цену за грамм.",
        )


# v0.3 routes resolve core._calculate_form at request time. Install validation in
# one place without changing their historical route implementations.
if not hasattr(core, "_validate_quote_inputs"):
    _base_calculate_form = core._calculate_form

    def _validated_calculate_form(db, data: dict):
        _validate_quote_inputs(data)
        return _base_calculate_form(db, data)

    core._validate_quote_inputs = _validate_quote_inputs
    core._calculate_form = _validated_calculate_form
else:
    _validate_quote_inputs = core._validate_quote_inputs


# Layer small UI overrides instead of rewriting the stable core route module.
loaders = []
for directory in (BASE_DIR / "templates_v06", BASE_DIR / "templates_v04"):
    if directory.exists():
        loaders.append(FileSystemLoader(str(directory)))
if loaders:
    core.templates.env.loader = ChoiceLoader([*loaders, core.templates.env.loader])


if not any(getattr(route, "path", None) == "/v04-static" for route in app.routes):
    app.mount("/v04-static", StaticFiles(directory=BASE_DIR / "v04_static"), name="v04-static")


if not any(
    getattr(route, "path", None) == "/api/import/3mf" and "POST" in getattr(route, "methods", set())
    for route in app.routes
):

    @app.post("/api/import/3mf")
    async def import_3mf(file: UploadFile = File(...)):
        try:
            file.file.seek(0)
            plates = import_bambu_3mf(file.file, file.filename or "")
            return {
                "filename": file.filename or "",
                "source": "bambu_studio_3mf",
                "plates": [plate.to_dict() for plate in plates],
            }
        except ThreeMFImportError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        finally:
            await file.close()


@app.get("/backup/restore", response_class=HTMLResponse)
def backup_restore_page(request: Request):
    return core.templates.TemplateResponse(request, "backup_restore.html", core.ctx(request))


async def _read_backup_upload(file: UploadFile) -> bytes:
    raw = await file.read(MAX_BACKUP_BYTES + 1)
    if len(raw) > MAX_BACKUP_BYTES:
        raise BackupValidationError("Backup больше 25 MiB; восстановление остановлено для безопасности.")
    return raw


@app.post("/api/backup/restore/preview")
async def backup_restore_preview(file: UploadFile = File(...)):
    try:
        raw = await _read_backup_upload(file)
        plan = validate_backup(raw)
        return plan.to_dict()
    except BackupValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        await file.close()


@app.post("/api/backup/restore/apply")
async def backup_restore_apply(
    file: UploadFile = File(...),
    confirmation_token: str = Form(...),
    confirmation_phrase: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        if confirmation_phrase != "RESTORE":
            raise BackupValidationError("Для восстановления требуется точная фраза RESTORE.")
        raw = await _read_backup_upload(file)
        plan = validate_backup(raw)
        result = apply_restore(db, plan, confirmation_token)
        return result
    except BackupValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        db.rollback()
        return JSONResponse(
            {"error": "Восстановление не выполнено: транзакция отменена, исходные данные сохранены."},
            status_code=500,
        )
    finally:
        await file.close()


@app.get("/home-assistant", response_class=HTMLResponse)
def home_assistant_page(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    return core.templates.TemplateResponse(
        request,
        "home_assistant.html",
        core.ctx(
            request,
            settings=settings,
            token_configured=bool(os.getenv("HOME_ASSISTANT_TOKEN", "").strip()),
        ),
    )


@app.post("/home-assistant")
async def home_assistant_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    enabled = form.get("home_assistant_enabled") == "on"
    base_url = str(form.get("home_assistant_url") or "").strip().rstrip("/")
    entity_id = str(form.get("home_assistant_energy_entity") or "").strip()
    if base_url and not base_url.startswith(("http://", "https://")):
        raise core.HTTPException(422, "Home Assistant URL должен начинаться с http:// или https://")
    if entity_id and "." not in entity_id:
        raise core.HTTPException(422, "Entity ID должен иметь вид sensor.example")
    set_setting(db, "home_assistant_enabled", enabled)
    set_setting(db, "home_assistant_url", base_url)
    set_setting(db, "home_assistant_energy_entity", entity_id)
    return RedirectResponse("/home-assistant", status_code=303)


@app.get("/api/orders/{order_id}/home-assistant-energy")
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
    token = os.getenv("HOME_ASSISTANT_TOKEN", "").strip()
    if not token:
        raise core.HTTPException(503, "На сервере не задан HOME_ASSISTANT_TOKEN.")

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
