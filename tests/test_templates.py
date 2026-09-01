from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def test_all_templates_parse():
    root = Path(__file__).resolve().parents[1] / "app" / "templates"
    env = Environment(loader=FileSystemLoader(root))
    for path in root.glob("*.html"):
        env.parse(path.read_text())


def test_v010_ui_assets_and_dashboard_structure_present():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app" / "templates" / "base.html").read_text()
    dashboard = (root / "app" / "templates" / "dashboard.html").read_text()
    css = (root / "app" / "static" / "v10.css").read_text()

    assert "/static/v10.css" in base
    assert "nav-caption" in base
    assert "dashboard-layout" in dashboard
    assert "Быстрые действия" in dashboard
    assert "--content-max" in css
    assert "@media(max-width:900px)" in css


def test_v011_ultrawide_real_device_overrides_present():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app" / "templates" / "base.html").read_text()
    css = (root / "app" / "static" / "v11.css").read_text()

    assert "/static/v11.css" in base
    assert "@media(min-width:2400px)" in css
    assert "@media(min-width:3000px)" in css
    assert "--content-max:3240px" in css
    assert "--sidebar-w:340px" in css
    assert ".filament-grid > .empty" in css
    assert "@media(max-width:900px)" in css


def test_v012_phone_real_device_polish_present():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app" / "templates" / "base.html").read_text()
    css = (root / "app" / "static" / "v12.css").read_text()
    settings = (root / "app" / "templates" / "settings.html").read_text()
    filaments = (root / "app" / "templates" / "filaments.html").read_text()
    system = (root / "app" / "templates" / "system_check.html").read_text()
    dashboard = (root / "app" / "templates" / "dashboard.html").read_text()
    js = (root / "app" / "static" / "app.js").read_text()

    assert "/static/v12.css" in base
    assert "--mobile-nav-h" in css
    assert ".mobile-dirty-save" in css
    assert ".system-check-head" in css
    assert "data-settings-form" in settings
    assert "data-mobile-collapsible" in settings
    assert "rate-explainer" in settings
    assert "data-open-details=\"#add-filament\"" in filaments
    assert "add-filament-card" in filaments
    assert "system-check-page" in system
    assert "payback-facts" in dashboard
    assert "setupSettingsForm" in js
    assert "setupDetailsActions" in js


def test_v013_3mf_local_filament_matching_ui_contract():
    root = Path(__file__).resolve().parents[1]
    importer = (root / "app" / "static" / "three_mf.js").read_text()
    app_js = (root / "app" / "static" / "app.js").read_text()
    order_form = (root / "app" / "templates" / "order_form.html").read_text()
    imports_router = (root / "app" / "routers" / "imports.py").read_text()

    assert "auto_local_filament_id" in importer
    assert "local_candidates" in importer
    assert "автоматически не угадываю" in importer
    assert "window.refreshRemainingWarnings" in app_js
    assert "window.invalidatePreview" in app_js
    assert '/static/three_mf.js' in order_form
    assert '"local_matching": "read_only_local_price_database"' in imports_router
    assert "match_local_filaments" in imports_router


def test_v013_actual_customer_price_economics_ui_contract():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text()
    order_form = (root / "app" / "templates" / "order_form.html").read_text()
    order_detail = (root / "app" / "templates" / "order_detail.html").read_text()
    economics_router = (root / "app" / "routers" / "economics.py").read_text()

    assert "/api/quotes/economics-preview" in app_js
    assert "previewCustomerEconomics" in order_form
    assert "Прибыль после окупаемости" in app_js
    assert "/customer-economics" in order_detail
    assert "saved_financial_snapshot" in economics_router
    assert "evaluate_customer_price" in economics_router


def test_v013_client_safe_quote_ui_contract():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "app" / "static" / "app.js").read_text()
    order_form = (root / "app" / "templates" / "order_form.html").read_text()
    order_detail = (root / "app" / "templates" / "order_detail.html").read_text()
    router = (root / "app" / "routers" / "client_quotes.py").read_text()

    assert "/api/quotes/client-message" in app_js
    assert "previewClientQuoteText" in order_form
    assert "copyPreviewClientQuote" in order_form
    assert "/client-message" in order_detail
    assert "copySavedClientQuote" in order_detail
    assert "navigator.clipboard" in app_js
    assert "document.execCommand('copy')" in app_js
    assert "build_client_quote" in router
