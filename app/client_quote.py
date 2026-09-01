from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ClientQuote:
    title: str
    customer_price: float
    print_minutes: int
    materials: list[str]
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _money(value: float) -> str:
    value = max(0.0, float(value))
    rounded = round(value)
    if abs(value - rounded) < 0.005:
        return f"{rounded} грн"
    return f"{value:.2f} грн"


def _duration(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} ч {mins} мин"
    if hours:
        return f"{hours} ч"
    return f"{mins} мин"


def _material_label(material: dict) -> str:
    family = str(material.get("material") or "").strip()
    name = str(material.get("name") or "").strip()
    if family and name:
        if family.casefold() in name.casefold():
            return name
        return f"{family} · {name}"
    return name or family or "Материал"


def build_client_quote(
    *,
    title: str,
    customer_price: float,
    print_minutes: int,
    materials: list[dict],
) -> ClientQuote:
    """Build a deliberately narrow, client-safe quote payload.

    This formatter accepts only customer-facing order facts. It has no access to
    pricing breakdowns, margins, taxes, risk reserves or equipment-payback data,
    which keeps accidental internal-cost leakage out of the generated message.
    """
    safe_title = str(title or "").strip() or "3D-печать на заказ"
    labels: list[str] = []
    seen: set[str] = set()
    for material in materials:
        label = _material_label(material)
        key = label.casefold()
        if key not in seen:
            labels.append(label)
            seen.add(key)

    material_line = ", ".join(labels) if labels else "не указан"
    noun = "Материалы" if len(labels) > 1 else "Материал"
    text = "\n".join(
        [
            f"3D-печать: {safe_title}",
            f"Стоимость: {_money(customer_price)}",
            f"Расчётное время печати: {_duration(print_minutes)}",
            f"{noun}: {material_line}",
            "Цена рассчитана для текущей версии модели и параметров печати.",
            "Срок готовности и доставка согласовываются отдельно.",
        ]
    )
    return ClientQuote(
        title=safe_title,
        customer_price=max(0.0, float(customer_price)),
        print_minutes=max(0, int(print_minutes)),
        materials=labels,
        text=text,
    )
