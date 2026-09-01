from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.three_mf import (
    ThreeMFImportError,
    import_bambu_3mf,
    match_local_filaments,
    normalize_material_name,
    parse_slice_info_xml,
)


SLICE_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="3972"/>
    <metadata key="weight" value="152.40"/>
    <filament id="1" tray_info_idx="GFL99" type="PETG" color="#000000" used_m="46.12" used_g="143.8" used_for_object="true" used_for_support="false"/>
    <filament id="2" tray_info_idx="GFS00" type="PLA-S" color="#FFFFFF" used_m="2.90" used_g="8.6" used_for_object="false" used_for_support="true"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="0"/>
  </plate>
</config>'''


def make_3mf(xml: bytes = SLICE_XML) -> BytesIO:
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        zf.writestr("Metadata/slice_info.config", xml)
    out.seek(0)
    return out


def spool(id: int, material: str, color: str, name: str):
    return SimpleNamespace(
        id=id,
        brand="SUNLU",
        name=name,
        material=material,
        color=color,
        price_per_g=0.65 + id / 100,
    )


def test_parse_slice_info_extracts_time_and_each_filament():
    plates = parse_slice_info_xml(SLICE_XML)
    assert len(plates) == 1
    plate = plates[0]
    assert plate.index == 1
    assert plate.prediction_seconds == 3972
    assert plate.print_minutes == 66
    assert round(plate.filament_total_g, 1) == 152.4
    assert [round(f.used_g, 1) for f in plate.filaments] == [143.8, 8.6]
    assert plate.filaments[1].type == "PLA-S"
    assert plate.filaments[1].used_for_support is True


def test_import_bambu_3mf_reads_only_slice_info():
    plates = import_bambu_3mf(make_3mf(), "test.gcode.3mf")
    assert plates[0].prediction_seconds == 3972
    assert plates[0].filaments[0].type == "PETG"


def test_import_rejects_unsliced_project():
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        zf.writestr("Metadata/project_settings.config", "{}")
    out.seek(0)
    with pytest.raises(ThreeMFImportError, match="slice_info.config"):
        import_bambu_3mf(out, "project.3mf")


def test_namespaced_config_is_supported():
    xml = b'''<x:config xmlns:x="urn:test"><x:plate><x:metadata key="index" value="3"/><x:metadata key="prediction" value="120"/><x:filament id="1" type="PLA" color="#fff" used_g="1.5"/></x:plate></x:config>'''
    plates = parse_slice_info_xml(xml)
    assert plates[0].index == 3
    assert plates[0].print_minutes == 2
    assert plates[0].filaments[0].used_g == 1.5


def test_material_normalization_ignores_punctuation_not_family():
    assert normalize_material_name("PETG-HF") == normalize_material_name("petg hf")
    assert normalize_material_name("PLA-S") != normalize_material_name("PLA")


def test_local_match_autoselects_unique_material():
    result = match_local_filaments("PETG", "#000000", [spool(1, "PETG", "Black", "PETG Black")])
    assert result["auto_select_id"] == 1
    assert result["auto_select_reason"] == "material"
    assert result["candidates"][0]["material"] == "PETG"


def test_local_match_prefers_unique_exact_color_among_same_material():
    result = match_local_filaments(
        "PETG",
        "#000000",
        [
            spool(1, "PETG", "#000000", "PETG Black"),
            spool(2, "PETG", "#FFFFFF", "PETG White"),
            spool(3, "PLA", "#000000", "PLA Black"),
        ],
    )
    assert [item["id"] for item in result["candidates"]] == [1, 2]
    assert result["auto_select_id"] == 1
    assert result["auto_select_reason"] == "material+color"


def test_local_match_keeps_ambiguous_material_manual():
    result = match_local_filaments(
        "PETG",
        "#123456",
        [spool(1, "PETG", "Black", "PETG Black"), spool(2, "PETG", "White", "PETG White")],
    )
    assert len(result["candidates"]) == 2
    assert result["auto_select_id"] is None
    assert result["auto_select_reason"] == ""
