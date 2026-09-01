from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import BinaryIO, Iterable
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

SLICE_INFO_PATH = "Metadata/slice_info.config"
MAX_SLICE_INFO_BYTES = 10 * 1024 * 1024


class ThreeMFImportError(ValueError):
    pass


@dataclass
class ImportedFilament:
    id: int | None
    type: str
    color: str
    used_g: float
    used_m: float | None = None
    tray_info_idx: str = ""
    used_for_support: bool | None = None
    used_for_object: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportedPlate:
    index: int
    prediction_seconds: int
    weight_g: float | None
    filaments: list[ImportedFilament]

    @property
    def print_minutes(self) -> int:
        # Bambu Studio stores prediction in seconds. Round to nearest minute for
        # the order form while keeping raw seconds in the API response.
        return max(0, int(round(self.prediction_seconds / 60.0)))

    @property
    def filament_total_g(self) -> float:
        return sum(item.used_g for item in self.filaments)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "prediction_seconds": self.prediction_seconds,
            "print_minutes": self.print_minutes,
            "weight_g": self.weight_g,
            "filament_total_g": self.filament_total_g,
            "filaments": [f.to_dict() for f in self.filaments],
        }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_float(raw: str | None, default: float | None = None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _to_int(raw: str | None, default: int | None = None) -> int | None:
    if raw is None or raw == "":
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _to_bool(raw: str | None) -> bool | None:
    if raw is None or raw == "":
        return None
    return raw.strip().lower() in {"1", "true", "yes"}


def normalize_material_name(value: str | None) -> str:
    """Normalize Bambu/local material labels without collapsing distinct families.

    This intentionally only ignores punctuation/spacing/case. For example,
    ``PETG-HF`` and ``PETG HF`` match, while ``PLA-S`` does not silently become
    generic ``PLA``. Ambiguous support/material aliases therefore stay manual.
    """
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _normalize_color(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def match_local_filaments(
    imported_type: str | None,
    imported_color: str | None,
    filaments: Iterable[object],
) -> dict:
    """Return safe local-price candidates and an optional unambiguous auto match.

    Auto-selection is deliberately conservative:
    - one active local filament with the exact normalized material => select it;
    - several material matches but exactly one exact normalized color => select it;
    - otherwise keep the row manual so the user chooses the real spool.
    """
    material_key = normalize_material_name(imported_type)
    if not material_key:
        return {"candidates": [], "auto_select_id": None, "auto_select_reason": ""}

    matches = [
        filament
        for filament in filaments
        if normalize_material_name(getattr(filament, "material", "")) == material_key
    ]
    matches.sort(
        key=lambda filament: (
            str(getattr(filament, "brand", "")).casefold(),
            str(getattr(filament, "name", "")).casefold(),
            int(getattr(filament, "id", 0) or 0),
        )
    )

    color_key = _normalize_color(imported_color)
    exact_color = []
    if color_key:
        exact_color = [
            filament
            for filament in matches
            if _normalize_color(getattr(filament, "color", "")) == color_key
        ]

    auto_select_id = None
    auto_select_reason = ""
    if len(exact_color) == 1:
        auto_select_id = int(getattr(exact_color[0], "id"))
        auto_select_reason = "material+color"
    elif len(matches) == 1:
        auto_select_id = int(getattr(matches[0], "id"))
        auto_select_reason = "material"

    candidates = []
    for filament in matches:
        brand = str(getattr(filament, "brand", "") or "").strip()
        name = str(getattr(filament, "name", "") or "").strip()
        material = str(getattr(filament, "material", "") or "").strip()
        color = str(getattr(filament, "color", "") or "").strip()
        label = " ".join(part for part in (brand, name) if part).strip() or material or "Филамент"
        if color:
            label = f"{label} · {color}"
        candidates.append(
            {
                "id": int(getattr(filament, "id")),
                "label": label,
                "brand": brand,
                "name": name,
                "material": material,
                "color": color,
                "price_per_g": float(getattr(filament, "price_per_g", 0.0) or 0.0),
            }
        )

    return {
        "candidates": candidates,
        "auto_select_id": auto_select_id,
        "auto_select_reason": auto_select_reason,
    }


def parse_slice_info_xml(xml_bytes: bytes) -> list[ImportedPlate]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ThreeMFImportError(f"Не удалось прочитать Metadata/slice_info.config: {exc}") from exc

    plates: list[ImportedPlate] = []
    for plate_el in root.iter():
        if _local_name(plate_el.tag) != "plate":
            continue

        metadata: dict[str, str] = {}
        filaments: list[ImportedFilament] = []
        for child in list(plate_el):
            tag = _local_name(child.tag)
            if tag == "metadata":
                key = child.attrib.get("key")
                if key:
                    metadata[key] = child.attrib.get("value", "")
            elif tag == "filament":
                used_g = _to_float(child.attrib.get("used_g"), 0.0) or 0.0
                # Ignore unused virtual/configured filament slots. Bambu Studio
                # writes the actual per-filament sliced usage in used_g.
                if used_g <= 0:
                    continue
                filaments.append(
                    ImportedFilament(
                        id=_to_int(child.attrib.get("id")),
                        type=child.attrib.get("type", "").strip(),
                        color=child.attrib.get("color", "").strip(),
                        used_g=used_g,
                        used_m=_to_float(child.attrib.get("used_m")),
                        tray_info_idx=child.attrib.get("tray_info_idx", "").strip(),
                        used_for_support=_to_bool(child.attrib.get("used_for_support")),
                        used_for_object=_to_bool(child.attrib.get("used_for_object")),
                    )
                )

        prediction = _to_int(metadata.get("prediction"), 0) or 0
        # slice_info may contain non-sliced plate blocks for project structure.
        # A usable sliced plate has a positive prediction or actual used filament.
        if prediction <= 0 and not filaments:
            continue

        plate_index = _to_int(metadata.get("index"), len(plates) + 1) or (len(plates) + 1)
        weight = _to_float(metadata.get("weight"))
        plates.append(
            ImportedPlate(
                index=plate_index,
                prediction_seconds=max(0, prediction),
                weight_g=weight,
                filaments=filaments,
            )
        )

    if not plates:
        raise ThreeMFImportError(
            "В slice_info.config не найдено нарезанных пластин. Сначала выполните Slice в Bambu Studio."
        )
    return plates


def import_bambu_3mf(file_obj: BinaryIO, filename: str = "") -> list[ImportedPlate]:
    if filename and not filename.lower().endswith(".3mf"):
        raise ThreeMFImportError("Нужен файл Bambu Studio с расширением .3mf")
    try:
        with ZipFile(file_obj) as archive:
            try:
                info = archive.getinfo(SLICE_INFO_PATH)
            except KeyError as exc:
                raise ThreeMFImportError(
                    "В 3MF нет Metadata/slice_info.config. Сохраните/экспортируйте проект после Slice в Bambu Studio."
                ) from exc
            if info.file_size > MAX_SLICE_INFO_BYTES:
                raise ThreeMFImportError("slice_info.config слишком большой; импорт остановлен для безопасности.")
            xml_bytes = archive.read(info)
    except BadZipFile as exc:
        raise ThreeMFImportError("Файл не является корректным 3MF/ZIP архивом.") from exc
    return parse_slice_info_xml(xml_bytes)
