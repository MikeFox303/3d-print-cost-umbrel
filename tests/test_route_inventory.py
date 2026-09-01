from app.server import app


def _routes():
    return {
        (getattr(route, "path", None), method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }


def test_public_route_inventory_is_stable():
    routes = _routes()
    expected = {
        ("/healthz", "GET"),
        ("/", "GET"),
        ("/stats", "GET"),
        ("/api/stats", "GET"),
        ("/exports/orders.csv", "GET"),
        ("/exports/backup.json", "GET"),
        ("/orders", "GET"),
        ("/orders", "POST"),
        ("/orders/new", "GET"),
        ("/orders/{order_id}/edit", "GET"),
        ("/orders/{order_id}/duplicate", "GET"),
        ("/orders/{order_id}", "GET"),
        ("/orders/{order_id}", "POST"),
        ("/orders/{order_id}/status", "POST"),
        ("/orders/{order_id}/archive", "POST"),
        ("/orders/{order_id}/trash", "POST"),
        ("/orders/{order_id}/restore", "POST"),
        ("/orders/{order_id}/delete", "POST"),
        ("/api/quotes/preview", "POST"),
        ("/api/quotes/economics-preview", "POST"),
        ("/api/quotes/client-message", "POST"),
        ("/api/orders/{order_id}/customer-economics", "GET"),
        ("/api/orders/{order_id}/client-message", "GET"),
        ("/filaments", "GET"),
        ("/filaments", "POST"),
        ("/filaments/{filament_id}/archive", "POST"),
        ("/settings", "GET"),
        ("/settings", "POST"),
        ("/api/spoolman/spools", "GET"),
        ("/api/import/3mf", "POST"),
        ("/backup/restore", "GET"),
        ("/api/backup/restore/preview", "POST"),
        ("/api/backup/restore/apply", "POST"),
        ("/system", "GET"),
        ("/api/system-check", "GET"),
        ("/home-assistant", "GET"),
        ("/home-assistant", "POST"),
        ("/api/orders/{order_id}/home-assistant-energy", "GET"),
    }
    missing = expected - routes
    assert not missing, f"Missing public routes: {sorted(missing)}"
