from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import __version__
from .db import Base, engine, get_db
from .models import Filament, Order, OrderMaterial, MonthlyPaybackRate
from .pricing import calculate_price, compute_realized_payback, get_or_create_monthly_payback_rate, round_customer_price
from .settings import DEFAULTS, ensure_defaults, get_settings, set_setting
from .integrations import ReadOnlySpoolmanClient

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
COMPLEXITY_LABELS = {"simple":"Простая","normal":"Обычная","complex":"Сложная","very_complex":"Очень сложная"}
PLATFORM_LABELS = {"direct":"Прямой заказ","olx_private":"OLX Доставка — частное","olx_business":"OLX Доставка — бизнес"}

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
    return {"request": request, "version": __version__, "status_labels": STATUS_LABELS, **kwargs}

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    orders = db.query(Order).filter(Order.deleted_at.is_(None)).order_by(Order.created_at.desc()).limit(8).all()
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
    settings = get_settings(db)
    filaments = db.query(Filament).filter(Filament.archived.is_(False)).order_by(Filament.brand, Filament.name).all()
    return templates.TemplateResponse(request, "order_form.html", ctx(request, settings=settings, filaments=filaments, order=None, complexity_labels=COMPLEXITY_LABELS, platform_labels=PLATFORM_LABELS))

def _parse_materials(db: Session, form) -> list[dict]:
    material_rows = []
    ids = form.getlist("filament_id")
    grams = form.getlist("grams")
    manual_names = form.getlist("manual_name")
    manual_prices = form.getlist("manual_price_per_g")
    max_len = max(len(ids), len(grams), len(manual_names), len(manual_prices), 0)
    for i in range(max_len):
        gram = float(grams[i] or 0) if i < len(grams) else 0
        if gram <= 0:
            continue
        fid = ids[i] if i < len(ids) else ""
        if fid:
            f = db.get(Filament, int(fid))
            if not f:
                continue
            material_rows.append({"filament": f, "name": f.name, "material": f.material, "grams": gram, "price_per_g": f.price_per_g})
        else:
            name = (manual_names[i] if i < len(manual_names) else "Материал") or "Материал"
            ppg = float(manual_prices[i] or 0) if i < len(manual_prices) else 0
            material_rows.append({"filament": None, "name": name, "material": "", "grams": gram, "price_per_g": ppg})
    return material_rows

@app.post("/orders")
async def order_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    title = str(form.get("title") or "Новый заказ").strip()
    print_hours = int(form.get("print_hours") or 0)
    print_mins = int(form.get("print_mins") or 0)
    manual_minutes = int(form.get("manual_minutes") or 0)
    packaging = float(form.get("packaging_cost") or 0)
    complexity = str(form.get("complexity") or "normal")
    platform = str(form.get("platform") or "direct")
    target_margin_raw = float(form.get("target_margin") or 35)
    target_margin = target_margin_raw / 100.0 if target_margin_raw > 1 else target_margin_raw
    final_price_raw = str(form.get("final_price") or "").strip()
    electricity_raw = str(form.get("electricity_kwh") or "").strip()
    final_price = float(final_price_raw) if final_price_raw else None
    electricity_kwh = float(electricity_raw) if electricity_raw else None
    materials = _parse_materials(db, form)
    settings = get_settings(db)
    breakdown = calculate_price(
        db, settings,
        print_minutes=print_hours*60+print_mins,
        manual_minutes=manual_minutes,
        packaging_cost=packaging,
        complexity=complexity,
        platform=platform,
        target_margin=target_margin,
        materials=materials,
        electricity_kwh=electricity_kwh,
    )
    if final_price is None:
        final_price = round_customer_price(breakdown.recommended_price)
    order = Order(
        title=title,
        client=str(form.get("client") or "").strip(),
        status=str(form.get("status") or "draft"),
        print_minutes=print_hours*60+print_mins,
        manual_minutes=manual_minutes,
        packaging_cost=packaging,
        complexity=complexity,
        platform=platform,
        electricity_kwh=electricity_kwh,
        target_margin=target_margin,
        final_price=final_price,
        production_cost=breakdown.production_cost,
        minimum_price=breakdown.minimum_price,
        recommended_price=breakdown.recommended_price,
        planned_payback=breakdown.planned_payback,
        expected_profit=breakdown.expected_profit,
        payback_rate_snapshot=breakdown.payback_rate,
        calc_snapshot_json=json.dumps(breakdown.to_dict(), ensure_ascii=False),
    )
    db.add(order)
    db.flush()
    for m in materials:
        f = m["filament"]
        db.add(OrderMaterial(
            order_id=order.id,
            filament_id=f.id if f else None,
            source="local" if f else "manual",
            name_snapshot=m["name"],
            material_snapshot=m["material"],
            grams=m["grams"],
            price_per_g_snapshot=m["price_per_g"],
        ))
    db.commit()
    return RedirectResponse(f"/orders/{order.id}", status_code=303)

@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    snap = json.loads(order.calc_snapshot_json or "{}")
    return templates.TemplateResponse(request, "order_detail.html", ctx(request, order=order, snap=snap, complexity_labels=COMPLEXITY_LABELS, platform_labels=PLATFORM_LABELS))

@app.post("/orders/{order_id}/status")
async def order_status(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404)
    form = await request.form()
    status = str(form.get("status") or order.status)
    settings = get_settings(db)
    order.status = status
    if status == "completed":
        order.completed_at = order.completed_at or datetime.utcnow()
        order.realized_payback = compute_realized_payback(order, settings)
    elif order.completed_at is not None:
        order.completed_at = None
        order.realized_payback = 0
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
    return templates.TemplateResponse(request, "filaments.html", ctx(request, filaments=filaments, settings=settings))

@app.post("/filaments")
async def filament_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    f = Filament(
        name=str(form.get("name") or "Филамент").strip(),
        brand=str(form.get("brand") or "").strip(),
        material=str(form.get("material") or "PETG").strip(),
        color=str(form.get("color") or "").strip(),
        weight_g=float(form.get("weight_g") or 1000),
        purchase_price=float(form.get("purchase_price") or 0),
    )
    db.add(f); db.commit()
    return RedirectResponse("/filaments", status_code=303)

@app.post("/filaments/{filament_id}/archive")
def filament_archive(filament_id: int, db: Session = Depends(get_db)):
    f = db.get(Filament, filament_id)
    if not f: raise HTTPException(404)
    f.archived = not f.archived
    db.commit()
    return RedirectResponse("/filaments", status_code=303)

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    settings = get_settings(db)
    rate = get_or_create_monthly_payback_rate(db, settings)
    return templates.TemplateResponse(request, "settings.html", ctx(request, settings=settings, current_rate=rate))

@app.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    types = {
        "equipment_cost": float, "payback_months": int, "payback_floor_hours_month": float,
        "payback_min_rate": float, "payback_max_rate": float, "payback_rolling_days": int,
        "extra_profit_payback_share": float, "material_reserve": float, "electricity_tariff": float,
        "average_power_w": float, "maintenance_per_hour": float, "labor_per_hour": float,
        "labor_min_per_order": float, "minimum_order_price": float, "tax_rate": float,
        "min_margin": float, "target_margin": float, "fixed_monthly_costs": float, "esv_monthly": float,
        "risk_simple": float, "risk_normal": float, "risk_complex": float, "risk_very_complex": float,
        "platform_olx_private_percent": float, "platform_olx_private_fixed": float, "platform_olx_private_cap": float,
        "platform_olx_business_percent": float, "platform_olx_business_fixed": float, "platform_olx_business_cap": float,
        "spoolman_url": str,
    }
    percent_fields = {"extra_profit_payback_share","material_reserve","tax_rate","min_margin","target_margin","risk_simple","risk_normal","risk_complex","risk_very_complex","platform_olx_private_percent","platform_olx_business_percent"}
    for key, typ in types.items():
        if key not in form: continue
        raw = str(form.get(key) or "").replace(",", ".")
        if raw == "": continue
        val = typ(raw)
        if key in percent_fields:
            val = val / 100.0
        set_setting(db, key, val)
    set_setting(db, "include_esv", "include_esv" in form)
    set_setting(db, "spoolman_enabled", "spoolman_enabled" in form)
    # Settings that affect the adaptive rate should recalc the current month immediately.
    month = datetime.utcnow().strftime("%Y-%m")
    db.query(MonthlyPaybackRate).filter_by(month=month).delete()
    db.commit()
    return RedirectResponse("/settings", status_code=303)

@app.get("/api/spoolman/spools")
async def spoolman_spools(db: Session = Depends(get_db)):
    settings = get_settings(db)
    if not bool(settings["spoolman_enabled"]):
        return JSONResponse({"enabled": False, "spools": []})
    try:
        client = ReadOnlySpoolmanClient(str(settings["spoolman_url"]))
        spools = await client.list_spools()
        return {"enabled": True, "read_only": True, "spools": spools}
    except Exception as exc:
        return JSONResponse({"enabled": True, "read_only": True, "error": str(exc), "spools": []}, status_code=502)
