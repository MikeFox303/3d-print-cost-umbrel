from __future__ import annotations

from . import main as core
from .routers.backup import router as backup_router
from .routers.home_assistant import router as home_assistant_router
from .routers.imports import router as imports_router
from .routers.system import router as system_router

app = core.app


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


# Core order routes predate validation. Keep one compatibility hook while the
# validation function is moved into the core module in the next refactor step.
if not hasattr(core, "_validate_quote_inputs"):
    _base_calculate_form = core._calculate_form

    def _validated_calculate_form(db, data: dict):
        _validate_quote_inputs(data)
        return _base_calculate_form(db, data)

    core._validate_quote_inputs = _validate_quote_inputs
    core._calculate_form = _validated_calculate_form
else:
    _validate_quote_inputs = core._validate_quote_inputs


for router in (imports_router, backup_router, system_router, home_assistant_router):
    app.include_router(router)
