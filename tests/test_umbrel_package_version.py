from pathlib import Path
import re

from app import __version__


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mikefox-3d-print-cost" / "umbrel-app.yml"
COMPOSE = ROOT / "mikefox-3d-print-cost" / "docker-compose.yml"


def _manifest_version(text: str) -> str:
    match = re.search(r'^version:\s*"([^"]+)"\s*$', text, re.MULTILINE)
    assert match, "Umbrel manifest version is missing"
    return match.group(1)


def _compose_image(text: str) -> str:
    match = re.search(r'^\s+image:\s*(\S+)\s*$', text, re.MULTILINE)
    assert match, "Umbrel compose image is missing"
    return match.group(1)


def test_umbrel_package_runtime_version_and_image_tag_are_aligned():
    manifest_text = MANIFEST.read_text()
    compose_text = COMPOSE.read_text()

    manifest_version = _manifest_version(manifest_text)
    image = _compose_image(compose_text)

    assert manifest_version == __version__
    assert image.startswith(
        f"ghcr.io/mikefox303/3d-print-cost-umbrel:{__version__}@sha256:"
    )


def test_umbrel_package_uses_immutable_digest_and_persistent_data_mount():
    compose_text = COMPOSE.read_text()
    image = _compose_image(compose_text)

    digest = image.split("@sha256:", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert "${APP_DATA_DIR}/data:/data" in compose_text
    assert "DATA_DIR: /data" in compose_text


def test_v013_release_notes_keep_external_integrations_read_only():
    manifest_text = MANIFEST.read_text()

    assert "Spoolman/Home Assistant remain read-only" in manifest_text
    assert "never reprices an order" in manifest_text
    assert "no schema migration is required" in manifest_text
