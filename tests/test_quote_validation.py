import pytest
from fastapi import HTTPException

from app.server import _validate_quote_inputs


def base_data():
    return {"print_minutes": 60, "materials": [{"name": "PETG", "price_per_g": 0.65}]}


def test_quote_requires_print_time():
    data = base_data(); data["print_minutes"] = 0
    with pytest.raises(HTTPException):
        _validate_quote_inputs(data)


def test_quote_requires_material_price():
    data = base_data(); data["materials"][0]["price_per_g"] = 0
    with pytest.raises(HTTPException, match="цена материала"):
        _validate_quote_inputs(data)
