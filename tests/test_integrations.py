from app.integrations import ReadOnlySpoolmanClient


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
