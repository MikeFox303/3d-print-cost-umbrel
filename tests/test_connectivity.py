from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "app" / "templates" / "base.html"
STATIC = ROOT / "app" / "static"


def test_shared_shell_contains_accessible_state_aware_connectivity_banner():
    base = BASE.read_text(encoding="utf-8")
    assert 'data-connectivity-banner' in base
    assert 'data-connectivity-title' in base
    assert 'data-connectivity-message' in base
    assert 'role="status"' in base
    assert 'aria-live="polite"' in base
    assert 'hidden' in base
    assert 'src="/static/connectivity.js"' in base
    assert 'Телефон офлайн.' in base
    assert 'Связь с Umbrel недоступна' in base


def test_connectivity_helper_distinguishes_device_and_umbrel_reachability():
    js = (STATIC / "connectivity.js").read_text(encoding="utf-8")
    assert "navigator.onLine === false" in js
    assert "state === 'device-offline'" in js
    assert "state === 'umbrel-unavailable'" in js
    assert "Телефон офлайн." in js
    assert "Umbrel недоступен." in js
    assert "VPN или Tailscale" in js
    assert "classList.toggle('is-offline', deviceOffline)" in js
    assert "classList.toggle('is-umbrel-unavailable', umbrelUnavailable)" in js


def test_connectivity_helper_probes_same_origin_health_without_cache():
    js = (STATIC / "connectivity.js").read_text(encoding="utf-8")
    assert "fetch('/healthz'" in js
    assert "method: 'GET'" in js
    assert "cache: 'no-store'" in js
    assert "Accept: 'application/json'" in js
    assert "payload?.status !== 'ok'" in js
    assert "PROBE_INTERVAL_MS = 15000" in js
    assert "PROBE_TIMEOUT_MS = 4000" in js
    assert "new AbortController()" in js
    assert "controller.abort()" in js


def test_connectivity_helper_rechecks_on_network_and_foreground_changes():
    js = (STATIC / "connectivity.js").read_text(encoding="utf-8")
    assert "addEventListener('offline', syncBrowserState)" in js
    assert "addEventListener('online', syncBrowserState)" in js
    assert "addEventListener('visibilitychange'" in js
    assert "document.visibilityState === 'visible'" in js
    assert "document.visibilityState !== 'hidden'" in js
    assert "window.setInterval" in js


def test_connectivity_helper_does_not_add_offline_business_storage():
    js = (STATIC / "connectivity.js").read_text(encoding="utf-8")
    forbidden = (
        "serviceWorker",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "CacheStorage",
    )
    for token in forbidden:
        assert token not in js


def test_connectivity_banner_has_safe_area_and_hidden_styles():
    css = (STATIC / "v14.css").read_text(encoding="utf-8")
    assert ".connection-banner" in css
    assert ".connection-banner[hidden]" in css
    assert "env(safe-area-inset-top)" in css
    assert "z-index: 2000" in css
