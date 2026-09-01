from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "app" / "templates" / "base.html"
STATIC = ROOT / "app" / "static"


def test_shared_shell_contains_accessible_connectivity_banner():
    base = BASE.read_text(encoding="utf-8")
    assert 'data-connectivity-banner' in base
    assert 'role="status"' in base
    assert 'aria-live="polite"' in base
    assert 'hidden' in base
    assert 'src="/static/connectivity.js"' in base
    assert 'Телефон офлайн.' in base
    assert 'Связь с Umbrel недоступна' in base


def test_connectivity_helper_tracks_browser_online_offline_events_only():
    js = (STATIC / "connectivity.js").read_text(encoding="utf-8")
    assert "navigator.onLine === false" in js
    assert "addEventListener('offline', sync)" in js
    assert "addEventListener('online', sync)" in js
    assert "banner.hidden = !offline" in js
    assert "classList.toggle('is-offline', offline)" in js

    forbidden = ("serviceWorker", "localStorage", "sessionStorage", "indexedDB")
    for token in forbidden:
        assert token not in js


def test_connectivity_banner_has_safe_area_and_hidden_styles():
    css = (STATIC / "v14.css").read_text(encoding="utf-8")
    assert ".connection-banner" in css
    assert ".connection-banner[hidden]" in css
    assert "env(safe-area-inset-top)" in css
    assert "z-index: 2000" in css
