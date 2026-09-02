from pathlib import Path
import re


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


def _image_version(image: str) -> str:
    match = re.fullmatch(
        r"ghcr\.io/mikefox303/3d-print-cost-umbrel:([^@\s]+)@sha256:([0-9a-f]{64})",
        image,
    )
    assert match, "Umbrel image must use the expected GHCR repo, a version tag and immutable SHA256 digest"
    return match.group(1)


def test_umbrel_manifest_and_pinned_image_version_are_aligned():
    manifest_text = MANIFEST.read_text()
    compose_text = COMPOSE.read_text()

    manifest_version = _manifest_version(manifest_text)
    image_version = _image_version(_compose_image(compose_text))

    assert manifest_version == image_version


def test_umbrel_package_uses_immutable_digest_and_persistent_data_mount():
    compose_text = COMPOSE.read_text()
    image = _compose_image(compose_text)

    assert _image_version(image)
    digest = image.split("@sha256:", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert "${APP_DATA_DIR}/data:/data" in compose_text
    assert "DATA_DIR: /data" in compose_text


def test_v014_release_notes_preserve_authoritative_server_and_read_only_integrations():
    manifest_text = MANIFEST.read_text()

    assert "there is no service worker or offline quote/order cache" in manifest_text
    assert "Umbrel/SQLite remains the authoritative source" in manifest_text
    assert "no schema migration is required" in manifest_text
    assert "Spoolman and Home Assistant remain read-only" in manifest_text
    assert "Bambuddy remains outside the quote/calculation workflow" in manifest_text
