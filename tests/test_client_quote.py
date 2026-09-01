import json

from app.client_quote import build_client_quote


FORBIDDEN_INTERNAL_TERMS = (
    "себесто",
    "марж",
    "налог",
    "комис",
    "окуп",
    "риск",
    "payback",
    "profit",
)


def test_client_quote_contains_only_customer_facing_facts():
    quote = build_client_quote(
        title="Крепление камеры",
        customer_price=540,
        print_minutes=185,
        materials=[
            {
                "name": "SUNLU Black",
                "material": "PETG",
                "price_per_g": 0.71,
                "base_cost": 123.45,
                "target_margin": 0.35,
            },
            {"name": "PLA Support", "material": "PLA"},
        ],
    )
    payload = json.dumps(quote.to_dict(), ensure_ascii=False).casefold()

    assert "Крепление камеры" in quote.text
    assert "540 грн" in quote.text
    assert "3 ч 5 мин" in quote.text
    assert "PETG · SUNLU Black" in quote.text
    assert "PLA Support" in quote.text
    for forbidden in FORBIDDEN_INTERNAL_TERMS:
        assert forbidden not in payload


def test_client_quote_deduplicates_material_labels():
    quote = build_client_quote(
        title="Деталь",
        customer_price=300,
        print_minutes=60,
        materials=[
            {"name": "PETG Black", "material": "PETG"},
            {"name": "PETG Black", "material": "PETG"},
        ],
    )
    assert quote.materials == ["PETG Black"]
    assert "Материал: PETG Black" in quote.text
    assert "Материалы:" not in quote.text


def test_client_quote_does_not_treat_print_time_as_delivery_deadline():
    quote = build_client_quote(
        title="Корпус",
        customer_price=425.5,
        print_minutes=45,
        materials=[],
    )
    assert "425.50 грн" in quote.text
    assert "Расчётное время печати: 45 мин" in quote.text
    assert "Срок готовности и доставка согласовываются отдельно" in quote.text
