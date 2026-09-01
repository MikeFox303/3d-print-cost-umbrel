import json
import struct
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.server import app


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
BASE = ROOT / "app" / "templates" / "base.html"


def test_v014_source_version_and_manifest_contract():
    assert __version__ == "0.14.0-dev.1"

    manifest = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["id"] == "/"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#0b1220"
    assert manifest["background_color"] == "#0b1220"
    assert {item["sizes"] for item in manifest["icons"]} == {"192x192", "512x512"}
    assert {item["src"] for item in manifest["icons"]} == {
        "/static/icons/icon-192.png",
        "/static/icons/icon-512.png",
    }
    shortcuts = {item["url"] for item in manifest["shortcuts"]}
    assert shortcuts == {"/orders/new", "/filaments"}


def test_every_page_base_links_ios_and_web_app_metadata():
    base = BASE.read_text(encoding="utf-8")
    assert 'rel="manifest" href="/static/manifest.webmanifest"' in base
    assert 'name="apple-mobile-web-app-capable" content="yes"' in base
    assert 'name="apple-mobile-web-app-status-bar-style" content="black-translucent"' in base
    assert 'name="apple-mobile-web-app-title" content="3D Print Cost"' in base
    assert 'rel="apple-touch-icon" sizes="180x180" href="/static/icons/apple-touch-icon.png"' in base
    assert 'href="/static/v14.css"' in base


def test_pwa_icons_exist_as_real_png_files_with_expected_dimensions():
    expected = {
        "apple-touch-icon.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
    }
    png_signature = b"\x89PNG\r\n\x1a\n"
    for filename, dimensions in expected.items():
        payload = (STATIC / "icons" / filename).read_bytes()
        assert payload.startswith(png_signature)
        assert len(payload) > 1000
        width, height = struct.unpack(">II", payload[16:24])
        assert (width, height) == dimensions


def test_standalone_shell_respects_ios_safe_area():
    css = (STATIC / "v14.css").read_text(encoding="utf-8")
    assert "display-mode: standalone" in css
    assert "env(safe-area-inset-top)" in css
    assert "100dvh" in css


def test_business_data_has_no_offline_service_worker_fallback():
    # v0.14 intentionally uses a manifest-only standalone shell. There is no
    # service worker, so HTML/forms/quotes/API responses always come from Umbrel.
    base = BASE.read_text(encoding="utf-8")
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "serviceWorker" not in base
    assert "serviceWorker" not in app_js
    assert not (STATIC / "sw.js").exists()
    assert not (STATIC / "service-worker.js").exists()


def test_dynamic_routes_are_no_store_but_static_manifest_is_not_forced_no_store():
    client = TestClient(app)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.headers.get("cache-control") == "no-store"
    assert health.headers.get("pragma") == "no-cache"

    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers.get("cache-control") != "no-store"
    assert manifest.json()["display"] == "standalone"
