import inspect

import pytest
from fastapi import HTTPException

from app import main, server


def test_server_registers_3mf_route():
    assert any(getattr(route, "path", None) == "/api/import/3mf" for route in server.app.routes)


def test_server_reexports_core_validation_without_monkeypatch():
    assert server._validate_quote_inputs is main._validate_quote_inputs
    source = inspect.getsource(server)
    assert "core._calculate_form =" not in source


def test_server_validation_rejects_zero_price():
    data = {"print_minutes": 60, "materials": [{"name": "PETG", "price_per_g": 0}]}
    with pytest.raises(HTTPException, match="цена материала"):
        server._validate_quote_inputs(data)
