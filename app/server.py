from __future__ import annotations

from pathlib import Path

from fastapi import File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, FileSystemLoader

from . import main as core
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


# Prefer the v0.4 order form while retaining every other template from the core app.
override_templates = BASE_DIR / "templates_v04"
if override_templates.exists():
    core.templates.env.loader = ChoiceLoader(
        [FileSystemLoader(str(override_templates)), core.templates.env.loader]
    )


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
