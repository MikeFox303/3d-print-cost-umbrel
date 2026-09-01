from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import main as core
from ..db import get_db
from ..pricing import PriceBreakdown, evaluate_customer_price, round_customer_price
from ..settings import get_settings

router = APIRouter()


def _breakdown_from_snapshot(order, snapshot: dict, settings: dict) -> PriceBreakdown:
    """Rebuild only the financial inputs needed for customer-price evaluation.

    New v0.13 snapshots contain every field below. Older snapshots use order
    columns/current fallback only where the historical snapshot did not contain
    a value; no database value is rewritten.
    """
    def number(key: str, fallback: float = 0.0) -> float:
        try:
            return float(snapshot.get(key, fallback) or 0.0)
        except (TypeError, ValueError):
            return float(fallback)

    return PriceBreakdown(
        material=number("material"),
        electricity=number("electricity"),
        maintenance=number("maintenance"),
        labor=number("labor"),
        packaging=number("packaging"),
        direct_cost=number("direct_cost"),
        risk_rate=number("risk_rate"),
        production_cost=number("production_cost", order.production_cost or 0.0),
        fixed_cost_share=number("fixed_cost_share"),
        base_cost=number("base_cost", order.production_cost or 0.0),
        payback_rate=number("payback_rate", order.payback_rate_snapshot or 0.0),
        planned_payback=number("planned_payback", order.planned_payback or 0.0),
        recommended_base=number(
            "recommended_base",
            number("base_cost", order.production_cost or 0.0) + float(order.planned_payback or 0.0),
        ),
        tax_rate=number("tax_rate", settings.get("tax_rate", 0.0)),
        platform_percent=number("platform_percent"),
        platform_fixed=number("platform_fixed"),
        platform_cap=number("platform_cap"),
        min_margin=number("min_margin"),
        target_margin=number("target_margin", order.target_margin or 0.0),
        minimum_price=number("minimum_price", order.minimum_price or 0.0),
        recommended_price=number("recommended_price", order.recommended_price or 0.0),
        extra_profit_payback_share=number(
            "extra_profit_payback_share",
            settings.get("extra_profit_payback_share", 0.0),
        ),
        expected_profit=number("expected_profit", order.expected_profit or 0.0),
    )


@router.post("/api/quotes/economics-preview")
async def quote_economics_preview(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = core._parse_order_form(db, form)
    settings, breakdown = core._calculate_form(db, data)
    customer_price = (
        float(data["final_price"])
        if data["final_price"] is not None
        else round_customer_price(breakdown.recommended_price)
    )
    economics = evaluate_customer_price(
        breakdown,
        customer_price,
        extra_profit_payback_share=float(settings["extra_profit_payback_share"]),
    )

    warnings = []
    for material in data["materials"]:
        remaining = material.get("remaining_g")
        if remaining is not None and material["grams"] > remaining:
            warnings.append(
                f"{material['name']}: требуется {material['grams']:.1f} г, "
                f"в Spoolman указано {remaining:.1f} г."
            )
    if not economics.meets_minimum_price:
        warnings.append(
            f"Цена клиенту ниже минимальной на {abs(economics.minimum_gap):.0f} грн. "
            "Заказ не достигает минимальной устойчивой цены."
        )
    elif not economics.meets_recommended_price:
        warnings.append(
            f"Цена клиенту ниже рекомендуемой на {abs(economics.recommended_gap):.0f} грн; "
            "вклад в окупаемость будет ниже плана."
        )

    return {
        "breakdown": breakdown.to_dict(),
        "minimum_price": breakdown.minimum_price,
        "recommended_price": breakdown.recommended_price,
        "recommended_rounded": round_customer_price(breakdown.recommended_price),
        "customer_price_source": "manual" if data["final_price"] is not None else "recommended_rounded",
        "customer_economics": economics.to_dict(),
        "warnings": warnings,
    }


@router.get("/api/orders/{order_id}/customer-economics")
def order_customer_economics(order_id: int, db: Session = Depends(get_db)):
    order = db.get(core.Order, order_id)
    if not order or order.deleted_at is not None:
        raise core.HTTPException(404)
    if order.final_price is None:
        raise core.HTTPException(409, "В заказе ещё нет цены клиенту.")

    try:
        snapshot = json.loads(order.calc_snapshot_json or "{}")
    except json.JSONDecodeError:
        snapshot = {}
    settings = get_settings(db)
    breakdown = _breakdown_from_snapshot(order, snapshot, settings)
    economics = evaluate_customer_price(breakdown, float(order.final_price))

    return {
        "order_id": order.id,
        "source": "saved_financial_snapshot",
        "snapshot_has_v013_share": "extra_profit_payback_share" in snapshot,
        "customer_economics": economics.to_dict(),
        "realized_payback": float(order.realized_payback or 0.0),
        "completed": order.status == "completed",
    }
