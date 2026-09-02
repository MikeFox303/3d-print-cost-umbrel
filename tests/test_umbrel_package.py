import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "mikefox-3d-print-cost"
# Immutable Community App package currently published for real-device validation.
# The digest comes from the successful multi-architecture main build of the
# matching runtime version and is intentionally pinned here as a release gate.
EXPECTED_VERSION = "0.14.0-dev.1"
EXPECTED_IMAGE_DIGEST = "sha256:ca7e5d0bc440b70d2f3d01869a7aa7bae96cf5290bdf4fd70391dd5a4b9b79c0"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_community_store_id_prefix_matches_package():
    store = read(ROOT / "umbrel-app-store.yml")
    manifest = read(PACKAGE / "umbrel-app.yml")
    assert 'id: "mikefox"' in store
    assert "id: mikefox-3d-print-cost" in manifest


def test_umbrel_compose_uses_current_legacy_compose_contract():
    compose = read(PACKAGE / "docker-compose.yml")
    assert compose.startswith('version: "3.7"')
    assert "APP_HOST: mikefox-3d-print-cost_web_1" in compose
    assert "APP_PORT: 8080" in compose
    assert "${APP_DATA_DIR}/data:/data" in compose
    assert "restart: on-failure" in compose
    assert "stop_grace_period: 30s" in compose
    assert "build:" not in compose
    assert "privileged:" not in compose
    assert "network_mode:" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "HOME_ASSISTANT_TOKEN" not in compose


def test_umbrel_manifest_is_browser_first_community_package():
    manifest = read(PACKAGE / "umbrel-app.yml")
    assert "manifestVersion: 1" in manifest
    assert f'version: "{EXPECTED_VERSION}"' in manifest
    assert "port: 8585" in manifest
    assert 'path: ""' in manifest
    assert "gallery: []" in manifest
    assert "icon: https://raw.githubusercontent.com/MikeFox303/3d-print-cost-umbrel/main/assets/icon.svg" in manifest


def test_umbrel_runtime_image_is_versioned_and_digest_pinned():
    compose = read(PACKAGE / "docker-compose.yml")
    expected = f"ghcr.io/mikefox303/3d-print-cost-umbrel:{EXPECTED_VERSION}@{EXPECTED_IMAGE_DIGEST}"
    assert expected in compose
    assert re.search(r"@sha256:[0-9a-f]{64}\b", compose)
    assert ":latest" not in compose


def test_manifest_and_pinned_runtime_use_the_same_package_version():
    manifest = read(PACKAGE / "umbrel-app.yml")
    compose = read(PACKAGE / "docker-compose.yml")
    manifest_match = re.search(r'^version:\s*"([^"]+)"', manifest, re.MULTILINE)
    image_match = re.search(r"3d-print-cost-umbrel:([^@\s]+)@sha256:", compose)
    assert manifest_match is not None
    assert image_match is not None
    assert manifest_match.group(1) == image_match.group(1) == EXPECTED_VERSION
