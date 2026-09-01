from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import main as core
from ..client_quote import build_client_quote
from ..db import get_db
from ..pricing import round_customer_price

router = APIRouter()


@router.post("/api/quotes/client-message")
async def client_quote_preview(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = core._parse_order_form(db, form)
    _, breakdown = core._calculate_form(db, data)
    customer_price = (
        float(data["final_price"])
        if data["final_price"] is not None
        else round_customer_price(breakdown.recommended_price)
    )
    quote = build_client_quote(
        title=data["title"],
        customer_price=customer_price,
        print_minutes=data["print_minutes"],
        materials=data["materials"],
    )
    return {"source": "quote_preview", **quote.to_dict()}


@router.get("/api/orders/{order_id}/client-message")
def saved_order_client_quote(order_id: int, db: Session = Depends(get_db)):
    order = db.get(core.Order, order_id)
    if not order or order.deleted_at is not None:
        raise core.HTTPException(404)
    if order.final_price is None:
        raise core.HTTPException(409, "В заказе ещё нет цены клиенту.")

    materials = [
        {"name": material.name_snapshot, "material": material.material_snapshot}
        for material in order.materials
    ]
    quote = build_client_quote(
        title=order.title,
        customer_price=float(order.final_price),
        print_minutes=order.print_minutes,
        materials=materials,
    )
    return {"source": "saved_order", "order_id": order.id, **quote.to_dict()}
