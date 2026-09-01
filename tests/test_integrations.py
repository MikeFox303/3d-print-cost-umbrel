from datetime import datetime, timedelta, timezone

import pytest

from app.integrations import (
    HomeAssistantReadOnlyError,
    ReadOnlyHomeAssistantClient,
    ReadOnlySpoolmanClient,
)


def test_spoolman_prefers_spool_price_and_initial_weight():
    item = ReadOnlySpoolmanClient.normalize_spool({
        "id": 17,
        "price": 650,
        "initial_weight": 950,
        "remaining_weight": 500,
        "filament": {
            "name": "PETG Black",
            "price": 700,
            "weight": 1000,
            "material": "PETG",
            "vendor": {"name": "SUNLU"},
        },
    })
    assert item["price"] == 650
    assert item["price_source"] == "spool"
    assert round(item["price_per_g"], 6) == round(650 / 950, 6)
    assert item["remaining_weight"] == 500


def test_spoolman_falls_back_to_filament_price_and_weight():
    item = ReadOnlySpoolmanClient.normalize_spool({
        "id": 18,
        "price": None,
        "initial_weight": None,
        "remaining_weight": 800,
        "filament": {
            "name": "PLA White",
            "price": 800,
            "weight": 1000,
            "material": "PLA",
            "vendor": {"name": "eSUN"},
        },
    })
    assert item["price"] == 800
    assert item["price_source"] == "filament"
    assert item["price_per_g"] == 0.8


def test_home_assistant_energy_delta_supports_meter_reset():
    start = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    samples = [
        (start, 10.0),
        (start + timedelta(minutes=30), 10.12),
        (start + timedelta(minutes=40), 0.02),
        (start + timedelta(hours=1), 0.08),
    ]
    kwh = ReadOnlyHomeAssistantClient.energy_from_samples(samples, "kWh", start, start + timedelta(hours=1))
    assert round(kwh, 3) == 0.20


def test_home_assistant_wh_is_converted_to_kwh():
    start = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    samples = [(start, 1000.0), (start + timedelta(hours=1), 1250.0)]
    assert ReadOnlyHomeAssistantClient.energy_from_samples(samples, "Wh", start, start + timedelta(hours=1)) == 0.25


def test_home_assistant_power_history_is_integrated():
    start = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    samples = [
        (start, 100.0),
        (start + timedelta(minutes=30), 200.0),
        (start + timedelta(hours=1), 100.0),
    ]
    kwh = ReadOnlyHomeAssistantClient.energy_from_samples(samples, "W", start, start + timedelta(hours=1))
    assert round(kwh, 3) == 0.15


def test_home_assistant_rejects_unsupported_unit_and_missing_token():
    start = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    with pytest.raises(HomeAssistantReadOnlyError, match="единица"):
        ReadOnlyHomeAssistantClient.energy_from_samples([(start, 1.0), (start + timedelta(minutes=1), 2.0)], "V", start, start + timedelta(minutes=1))
    with pytest.raises(HomeAssistantReadOnlyError, match="TOKEN"):
        ReadOnlyHomeAssistantClient("http://ha.local:8123", "")


def test_home_assistant_numeric_samples_skip_unavailable_values():
    rows = [
        {"state": "unavailable", "last_changed": "2026-09-01T10:00:00Z"},
        {"state": "100", "last_changed": "2026-09-01T10:01:00Z"},
        {"state": "bad", "last_changed": "2026-09-01T10:02:00Z"},
    ]
    samples = ReadOnlyHomeAssistantClient._numeric_samples(rows)
    assert len(samples) == 1
    assert samples[0][1] == 100.0
