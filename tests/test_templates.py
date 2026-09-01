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
