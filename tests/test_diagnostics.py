import json

from sqlalchemy import create_engine

from app.diagnostics import build_system_check
from app.migrations import run_migrations
from app.server import app


def test_system_check_reports_runtime_without_leaking_secret(tmp_path, monkeypatch):
    db_path = tmp_path / "diagnostics.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    run_migrations(test_engine, safety_dir=tmp_path / "migration-safety")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "super-secret-token")

    settings = {
        "spoolman_enabled": True,
        "spoolman_url": "http://spoolman.local:7912",
        "home_assistant_enabled": True,
        "home_assistant_url": "http://homeassistant.local:8123",
        "home_assistant_energy_entity": "sensor.x2d_energy",
    }
    report = build_system_check(settings, db_engine=test_engine, data_dir=tmp_path)

    assert report["status"] == "ok"
    assert report["storage"]["writable"] is True
    assert report["database"]["reachable"] is True
    assert report["database"]["name"] == "diagnostics.db"
    assert report["migrations"]["up_to_date"] is True
    assert report["integrations"]["spoolman"]["read_only"] is True
    assert report["integrations"]["home_assistant"]["read_only"] is True
    assert report["integrations"]["home_assistant"]["token_configured"] is True
    assert report["integrations"]["home_assistant"]["token_source"] == "environment"
    assert report["secrets_exposed"] is False
    assert report["network_requests_performed"] is False
    assert "super-secret-token" not in json.dumps(report)
    assert "spoolman.local" not in json.dumps(report)
    assert "homeassistant.local" not in json.dumps(report)


def test_enabled_but_incomplete_integration_is_warning(tmp_path, monkeypatch):
    db_path = tmp_path / "diagnostics.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    run_migrations(test_engine)
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)

    report = build_system_check(
        {
            "spoolman_enabled": True,
            "spoolman_url": "",
            "home_assistant_enabled": True,
            "home_assistant_url": "http://homeassistant.local:8123",
            "home_assistant_energy_entity": "sensor.x2d_energy",
        },
        db_engine=test_engine,
        data_dir=tmp_path,
    )

    assert report["checks"]["persistent_storage"] == "ok"
    assert report["checks"]["database"] == "ok"
    assert report["checks"]["migrations"] == "ok"
    assert report["checks"]["spoolman"] == "warning"
    assert report["checks"]["home_assistant"] == "warning"
    assert report["status"] == "degraded"


def test_system_check_routes_are_registered():
    routes = [
        (getattr(route, "path", None), set(getattr(route, "methods", set()) or set()))
        for route in app.routes
    ]
    assert any(path == "/system" and "GET" in methods for path, methods in routes)
    assert any(path == "/api/system-check" and "GET" in methods for path, methods in routes)
