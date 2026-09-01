from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import __version__
from .analytics import build_business_stats
from .db import Base, engine, get_db
from .integrations import ReadOnlySpoolmanClient
from .models import Filament, MonthlyPaybackRate, Order, OrderMaterial
from .pricing import (
    calculate_price,
    compute_realized_payback,
    get_or_create_monthly_payback_rate,
    round_customer_price,
)
from .settings import ensure_defaults, get_settings, set_setting

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="3D Print Cost", version=__version__)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STATUS_LABELS = {
    "draft": "Черновик",
    "quoted": "Цена отправлена",
    "accepted": "Принят",
    "printing": "Печатается",
    "completed": "Выполнен",
    "cancelled": "Отменён",
}
COMPLEXITY_LABELS = {
    "simple": "Простая",
    "normal": "Обычная",
    "complex": "Сложная",
    "very_complex": "Очень сложная",
}
PLATFORM_LABELS = {
    "direct": "Прямой заказ",
    "olx_private": "OLX Доставка — частное",
    "olx_business": "OLX Доставка — бизнес",
}


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    from .db import SessionLocal

    with SessionLocal() as db:
        ensure_defaults(db)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}


def ctx(request: Request, **kwargs):
    return {
        "request": request,
        "version": __version__,
        "status_labels": STATUS_LABELS,
        **kwargs,
    }


def _to_int(raw, default: int = 0) -> int:
    try:
        return int(float(str(raw or default).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _to_float(raw, default: float = 0.0) -> float:
    try:
        return float(str(raw if raw not in (None, "") else default).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _optional_float(raw) -> float | None:
    if raw in (None, ""):
        return None
    return _to_float(raw)


def _form_context(
    request: Request,
    db: Session,
    *,
    order: Order | None = None,
    duplicate: bool = False,
):
    settings = get_settings(db)
    filaments = (
        db.query(Filament)
        .filter(Filament.archived.is_(False))
        .order_by(Filament.brand, Filament.name)
        .all()
    )
    if order is None:
        form_action = "/orders"
        page_title = "Новый заказ"
        submit_label = "Сохранить заказ"
        prefill_title = ""
    elif duplicate:
        form_action = "/orders"
        page_title = f"Дублировать заказ #{order.id:04d}"
        submit_label = "Создать копию"
        prefill_title = f"{order.title} — копия"
    else:
        form_action = f"/orders/{order.id}"
        page_title = f"Редактировать заказ #{order.id:04d}"
        submit_label = "Сохранить изменения"
        prefill_title = order.title

    return ctx(
        request,
        settings=settings,
        filaments=filaments,
        order=order,
        duplicate=duplicate,
        form_action=form_action,
        page_title=page_title,
        submit_label=submit_label,
        prefill_title=prefill_title,
        complexity_labels=COMPLEXITY_LABELS,
        platform_labels=PLATFORM_LABELS,
    )


def _parse_materials(db: Session, form) -> list[dict]:
    material_rows: list[dict] = []
    ids = form.getlist("filament_id")
    grams = form.getlist("grams")
    manual_names = form.getlist("manual_name")
    manual_materials = form.getlist("manual_material")
    manual_prices = form.getlist("manual_price_per_g")
    sources = form.getlist("material_source")
    refs = form.getlist("material_source_ref")
    remaining = form.getlist("remaining_g")
    max_len = max(
        len(ids), len(grams), len(manual_names), len(manual_materials),
        len(manual_prices), len(sources), len(refs), len(remaining), 0,
    )
    for i in range(max_len):
        gram = _to_float(grams[i] if i < len(grams) else 0)
        if gram <= 0:
            continue
        fid = ids[i] if i < len(ids) else ""
        if fid:
            f = db.get(Filament, _to_int(fid))
            if not f:
                continue
            material_rows.append({
                "filament": f,
                "source": "local",
                "source_ref": str(f.id),
                "name": f.name,
                "material": f.material,
                "grams": gram,
                "price_per_g": f.price_per_g,
                "remaining_g": None,
            })
            continue

        name = (manual_names[i] if i < len(manual_names) else "Материал") or "Материал"
        material_type = (manual_materials[i] if i < len(manual_materials) else "") or ""
        ppg = _to_float(manual_prices[i] if i < len(manual_prices) else 0)
        source = (sources[i] if i < len(sources) else "manual") or "manual"
        if source not in {"manual", "spoolman"}:
            source = "manual"
        source_ref = (refs[i] if i < len(refs) else "") or ""
        remaining_g = _optional_float(remaining[i] if i < len(remaining) else None)
        material_rows.append({
            "filament": None,
            "source": source,
            "source_ref": source_ref,
            "name": name,
            "material": material_type,
            "grams": gram,
            "price_per_g": ppg,
            "remaining_g": remaining_g,
        })
    return material_rows


def _parse_order_form(db: Session, form) -> dict:
    target_margin_raw = _to_float(form.get("target_margin"), 35)
    target_margin = target_margin_raw / 100.0 if target_margin_raw > 1 else target_margin_raw
    return {
        "title": str(form.get("title") or "Новый заказ").strip(),
        "client": str(form.get("client") or "").strip(),
        "status": str(form.get("status") or "draft"),
        "print_minutes": _to_int(form.get("print_hours")) * 60 + _to_int(form.get("print_mins")),
        "manual_minutes": _to_int(form.get("manual_minutes")),
        "packaging_cost": _to_float(form.get("packaging_cost")),
        "complexity": str(form.get("complexity") or "normal"),
        "platform": str(form.get("platform") or "direct"),
        "target_margin": target_margin,
        "final_price": _optional_float(form.get("final_price")),
        "electricity_kwh": _optional_float(form.get("electricity_kwh")),
        "materials": _parse_materials(db, form),
    }


def _calculate_form(db: Session, data: dict):
    settings = get_settings(db)
    breakdown = calculate_price(
        db,
        settings,
        print_minutes=data["print_minutes"],
        manual_minutes=data["manual_minutes"],
        packaging_cost=data["packaging_cost"],
        complexity=data["complexity"],
        platform=data["platform"],
        target_margin=data["target_margin"],
        materials=data["materials"],
        electricity_kwh=data["electricity_kwh"],
    )
    return settings, breakdown


def _apply_order(order: Order, data: dict, breakdown) -> None:
    order.title = data["title"]
    order.client = data["client"]
    order.status = data["status"]
    order.print_minutes = data["print_minutes"]
    order.manual_minutes = data["manual_minutes"]
    order.packaging_cost = data["packaging_cost"]
    order.complexity = data["complexity"]
    order.platform = data["platform"]
    order.electricity_kwh = data["electricity_kwh"]
    order.target_margin = data["target_margin"]
    order.final_price = data["final_price"] if data["final_price"] is not None else round_customer_price(breakdown.recommended_price)
    order.production_cost = breakdown.production_cost
    order.minimum_price = breakdown.minimum_price
    order.recommended_price = breakdown.recommended_price
    order.planned_payback = breakdown.planned_payback
    order.expected_profit = breakdown.expected_profit
    order.payback_rate_snapshot = breakdown.payback_rate
    order.calc_snapshot_json = json.dumps(breakdown.to_dict(), ensure_ascii=False)


def _replace_materials(db: Session, order: Order, materials: list[dict]) -> None:
    db.query(OrderMaterial).filter(OrderMaterial.order_id == order.id).delete(synchronize_session=False)
    for m in materials:
        f = m["filament"]
        db.add(OrderMaterial(
            order_id=order.id,
            filament_id=f.id if f else None,
            source=m["source"],
            source_ref=m["source_ref"],
            name_snapshot=m["name"],
            material_snapshot=m["material"],
            grams=m["grams"],
            price_per_g_snapshot=m["price_per_g"],
            remaining_g_snapshot=m["remaining_g"],
        ))


def _sync_completion(order: Order, settings: dict) -> None:
    if order.status == "completed":
        order.completed_at = order.completed_at or datetime.utcnow()
        order.realized_payback = compute_realized_payback(order, settings)
    else:
        order.completed_at = None
        order.realized_payback = 0.0


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    orders = (
        db.query(Order)
        .filter(Order.deleted_at.is_(None))
        .order_by(Order.created_at.desc())
        .limit(8)
        .all()
    )
    completed = db.query(Order).filter(Order.status == "completed", Order.deleted_at.is_(None)).all()
    revenue = sum(o.final_price or 0 for o in completed)
    recovered = sum(o.realized_payback or 0 for o in completed)
    equipment_cost = float(settings["equipment_cost"])
    current_rate = get_or_create_monthly_payback_rate(db, settings)
    stats = {
        "orders": len(completed),
        "revenue": revenue,
        "recovered": recovered,
        "equipment_cost": equipment_cost,
        "payback_percent": min(100.0, recovered / equipment_cost * 100) if equipment_cost else 100,
        "current_rate": current_rate,
    }
    return templates.TemplateResponse(request, "dashboard.html", ctx(request, orders=orders, stats=stats))


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    stats = build_business_stats(db, settings)
    return templates.TemplateResponse(request, "stats.html", ctx(request, stats=stats))


@app.get("/api/stats")
def stats_api(db: Session = Depends(get_db)):
    settings = get_settings(db)
    return build_business_stats(db, settings).to_dict()


def _iso(value):
    return value.isoformat() if value is not None else None


@app.get("/exports/orders.csv")
def export_orders_csv(db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "created_at", "completed_at", "status", "title", "client",
        "print_hours", "materials", "production_cost", "minimum_price",
        "recommended_price", "final_price", "planned_payback", "realized_payback",
    ])
    orders = db.query(Order).filter(Order.deleted_at.is_(None)).order_by(Order.id).all()
    for order in orders:
        materials = "; ".join(
            f"{m.name_snapshot}: {m.grams:.1f} g @ {m.price_per_g_snapshot:.4f}"
            for m in order.materials
        )
        writer.writerow([
            order.id, _iso(order.created_at), _iso(order.completed_at), order.status,
            order.title, order.client, round(order.print_minutes / 60.0, 3), materials,
            round(order.production_cost or 0, 2), round(order.minimum_price or 0, 2),
            round(order.recommended_price or 0, 2),
            round(order.final_price, 2) if order.final_price is not None else "",
            round(order.planned_payback or 0, 2), round(order.realized_payback or 0, 2),
        ])
    payload = "\ufeff" + output.getvalue()
    headers = {"Content-Disposition": 'attachment; filename="3d-print-orders.csv"'}
    return StreamingResponse(iter([payload]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/exports/backup.json")
def export_backup_json(db: Session = Depends(get_db)):
    settings = get_settings(db)
    filaments = db.query(Filament).order_by(Filament.id).all()
    orders = db.query(Order).order_by(Order.id).all()
    monthly_rates = db.query(MonthlyPaybackRate).order_by(MonthlyPaybackRate.month).all()
    data = {
        "schema": "3d-print-cost-backup-v1",
        "app_version": __version__,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "settings": settings,
        "filaments": [
            {
                "id": f.id, "name": f.name, "brand": f.brand, "material": f.material,
                "color": f.color, "weight_g": f.weight_g, "purchase_price": f.purchase_price,
                "archived": f.archived, "created_at": _iso(f.created_at),
            } for f in filaments
        ],
        "orders": [
            {
                "id": o.id, "title": o.title, "client": o.client, "status": o.status,
                "print_minutes": o.print_minutes, "manual_minutes": o.manual_minutes,
                "packaging_cost": o.packaging_cost, "complexity": o.complexity,
                "platform": o.platform, "electricity_kwh": o.electricity_kwh,
                "target_margin": o.target_margin, "final_price": o.final_price,
                "production_cost": o.production_cost, "minimum_price": o.minimum_price,
                "recommended_price": o.recommended_price, "planned_payback": o.planned_payback,
                "realized_payback": o.realized_payback, "expected_profit": o.expected_profit,
                "payback_rate_snapshot": o.payback_rate_snapshot,
                "calc_snapshot_json": o.calc_snapshot_json, "archived": o.archived,
                "deleted_at": _iso(o.deleted_at), "created_at": _iso(o.created_at),
                "updated_at": _iso(o.updated_at), "completed_at": _iso(o.completed_at),
                "materials": [
                    {
                        "filament_id": m.filament_id, "source": m.source,
                        "source_ref": m.source_ref, "name_snapshot": m.name_snapshot,
                        "material_snapshot": m.material_snapshot, "grams": m.grams,
                        "price_per_g_snapshot": m.price_per_g_snapshot,
                        "remaining_g_snapshot": m.remaining_g_snapshot,
                    } for m in o.materials
                ],
            } for o in orders
        ],
        "monthly_payback_rates": [
            {
                "month": r.month, "rate": r.rate, "reference_hours": r.reference_hours,
                "remaining_equipment": r.remaining_equipment,
                "recovered_before": r.recovered_before, "created_at": _iso(r.created_at),
            } for r in monthly_rates
        ],
    }
    headers = {"Content-Disposition": 'attachment; filename="3d-print-cost-backup.json"'}
    return JSONResponse(data, headers=headers)


@app.get("/orders", response_class=HTMLResponse)
def orders_list(request: Request, view: str = "active", db: Session = Depends(get_db)):
    q = db.query(Order)
    if view == "trash":
        q = q.filter(Order.deleted_at.isnot(None))
    elif view == "archive":
        q = q.filter(Order.deleted_at.is_(None), Order.archived.is_(True))
    else:
        q = q.filter(Order.deleted_at.is_(None), Order.archived.is_(False))
    orders = q.order_by(Order.created_at.desc()).all()
    return templates.TemplateResponse(request, "orders.html", ctx(request, orders=orders, view=view))


@app.get("/orders/new", response_class=HTMLResponse)
def order_new(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "order_form.html", _form_context(request, db))


@app.get("/orders/{order_id}/edit", response_class=HTMLResponse)
def order_edit(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(404)
    if order.status == "completed":
        raise HTTPException(409, "Выполненный заказ защищён от редактирования. Создайте копию заказа.")
    return templates.TemplateResponse(request, "order_form.html", _form_context(request, db, order=order))


@app.get("/orders/{order_id}/duplicate", response_class=HTMLResponse)
def order_duplicate(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "order_form.html", _form_context(request, db, order=order, duplicate=True))


@app.post("/api/quotes/preview")
async def quote_preview(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = _parse_order_form(db, form)
    _, breakdown = _calculate_form(db, data)
    warnings = []
    for m in data["materials"]:
        remaining = m.get("remaining_g")
        if remaining is not None and m["grams"] > remaining:
            warnings.append(
                f"{m['name']}: требуется {m['grams']:.1f} г, в Spoolman указано {remaining:.1f} г."
            )
    return {
        "breakdown": breakdown.to_dict(),
        "minimum_price": breakdown.minimum_price,
        "recommended_price": breakdown.recommended_price,
        "recommended_rounded": round_customer_price(breakdown.recommended_price),
        "warnings": warnings,
    }


@app.post("/orders")
async def order_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = _parse_order_form(db, form)
    settings, breakdown = _calculate_form(db, data)
    order = Order()
    _apply_order(order, data, breakdown)
    db.add(order)
    db.flush()
    _replace_materials(db, order, data["materials"])
    _sync_completion(order, settings)
    db.commit()
    return RedirectResponse(f"/orders/{order.id}", status_code=303)


@app.post("/orders/{order_id}")
async def order_update(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(404)
    if order.status == "completed":
        raise HTTPException(409, "Выполненный заказ защищён от редактирования. Создайте копию заказа.")
    form = await request.form()
    data = _parse_order_form(db, form)
    settings, breakdown = _calculate_form(db, data)
    _apply_order(order, data, breakdown)
    _replace_materials(db, order, data["materials"])
    _sync_completion(order, settings)
    db.commit()
    return RedirectResponse(f"/orders/{order.id}", status_code=303)


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    snap = json.loads(order.calc_snapshot_json or "{}")
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        ctx(
            request,
            order=order,
            snap=snap,
            complexity_labels=COMPLEXITY_LABELS,
            platform_labels=PLATFORM_LABELS,
        ),
    )


@app.post("/orders/{order_id}/status")
async def order_status(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    form = await request.form()
    status = str(form.get("status") or order.status)
    settings = get_settings(db)
    order.status = status
    _sync_completion(order, settings)
    db.commit()
    return RedirectResponse(f"/orders/{order.id}", status_code=303)


@app.post("/orders/{order_id}/archive")
def order_archive(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    order.archived = not order.archived
    db.commit()
    return RedirectResponse("/orders", status_code=303)


@app.post("/orders/{order_id}/trash")
def order_trash(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    order.deleted_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/orders", status_code=303)


@app.post("/orders/{order_id}/restore")
def order_restore(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    order.deleted_at = None
    db.commit()
    return RedirectResponse("/orders?view=trash", status_code=303)


@app.post("/orders/{order_id}/delete")
def order_delete(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    db.delete(order)
    db.commit()
    return RedirectResponse("/orders?view=trash", status_code=303)


@app.get("/filaments", response_class=HTMLResponse)
def filaments_page(request: Request, db: Session = Depends(get_db)):
    filaments = db.query(Filament).order_by(Filament.archived, Filament.brand, Filament.name).all()
    settings = get_settings(db)
    return templates.TemplateResponse(
        request, "filaments.html", ctx(request, filaments=filaments, settings=settings)
    )


@app.post("/filaments")
async def filament_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    f = Filament(
        name=str(form.get("name") or "Филамент").strip(),
        brand=str(form.get("brand") or "").strip(),
        material=str(form.get("material") or "PETG").strip(),
        color=str(form.get("color") or "").strip(),
        weight_g=_to_float(form.get("weight_g"), 1000),
        purchase_price=_to_float(form.get("purchase_price")),
    )
    db.add(f)
    db.commit()
    return RedirectResponse("/filaments", status_code=303)


@app.post("/filaments/{filament_id}/archive")
def filament_archive(filament_id: int, db: Session = Depends(get_db)):
    f = db.get(Filament, filament_id)
    if not f:
        raise HTTPException(404)
    f.archived = not f.archived
    db.commit()
    return RedirectResponse("/filaments", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    rate = get_or_create_monthly_payback_rate(db, settings)
    return templates.TemplateResponse(
        request, "settings.html", ctx(request, settings=settings, current_rate=rate)
    )


@app.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    types = {
        "equipment_cost": float,
        "payback_months": int,
        "payback_floor_hours_month": float,
        "payback_min_rate": float,
        "payback_max_rate": float,
        "payback_rolling_days": int,
        "extra_profit_payback_share": float,
        "material_reserve": float,
        "electricity_tariff": float,
        "average_power_w": float,
        "maintenance_per_hour": float,
        "labor_per_hour": float,
        "labor_min_per_order": float,
        "minimum_order_price": float,
        "tax_rate": float,
        "min_margin": float,
        "target_margin": float,
        "fixed_monthly_costs": float,
        "esv_monthly": float,
        "risk_simple": float,
        "risk_normal": float,
        "risk_complex": float,
        "risk_very_complex": float,
        "platform_olx_private_percent": float,
        "platform_olx_private_fixed": float,
        "platform_olx_private_cap": float,
        "platform_olx_business_percent": float,
        "platform_olx_business_fixed": float,
        "platform_olx_business_cap": float,
        "spoolman_url": str,
    }
    percent_fields = {
        "extra_profit_payback_share",
        "material_reserve",
        "tax_rate",
        "min_margin",
        "target_margin",
        "risk_simple",
        "risk_normal",
        "risk_complex",
        "risk_very_complex",
        "platform_olx_private_percent",
        "platform_olx_business_percent",
    }
    for key, typ in types.items():
        if key not in form:
            continue
        raw = str(form.get(key) or "").replace(",", ".")
        if raw == "":
            continue
        val = typ(raw)
        if key in percent_fields:
            val = val / 100.0
        set_setting(db, key, val)
    set_setting(db, "include_esv", "include_esv" in form)
    set_setting(db, "spoolman_enabled", "spoolman_enabled" in form)
    month = datetime.utcnow().strftime("%Y-%m")
    db.query(MonthlyPaybackRate).filter_by(month=month).delete()
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.get("/api/spoolman/spools")
async def spoolman_spools(db: Session = Depends(get_db)):
    settings = get_settings(db)
    if not bool(settings["spoolman_enabled"]):
        return JSONResponse({"enabled": False, "read_only": True, "spools": []})
    try:
        client = ReadOnlySpoolmanClient(str(settings["spoolman_url"]))
        spools = await client.list_spools()
        return {"enabled": True, "read_only": True, "spools": spools}
    except Exception as exc:
        return JSONResponse(
            {"enabled": True, "read_only": True, "error": str(exc), "spools": []},
            status_code=502,
        )
