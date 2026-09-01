import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "mikefox-3d-print-cost"
EXPECTED_VERSION = "0.10.0-dev.1"
EXPECTED_IMAGE_DIGEST = "sha256:e2288a7480576313beaeac82242528a5c4b60c7ffe24b3b2385d93d49be0cc0b"


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


def test_manifest_and_runtime_version_match_application_version():
    app_version = {}
    exec(read(ROOT / "app" / "__init__.py"), app_version)
    assert app_version["__version__"] == EXPECTED_VERSION
