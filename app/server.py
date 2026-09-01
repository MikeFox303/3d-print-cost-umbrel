from __future__ import annotations

from fastapi import Request

from . import main as core
from .routers.backup import router as backup_router
from .routers.client_quotes import router as client_quotes_router
from .routers.economics import router as economics_router
from .routers.home_assistant import router as home_assistant_router
from .routers.imports import router as imports_router
from .routers.system import router as system_router

app = core.app
_validate_quote_inputs = core._validate_quote_inputs


@app.middleware("http")
async def no_store_dynamic_business_responses(request: Request, call_next):
    """Keep browser/PWA caches from becoming a second source of business truth.

    Static presentation assets may use normal browser caching. Every dynamic
    route—including HTML forms and JSON APIs—is explicitly no-store so Umbrel
    remains authoritative when the phone is used as a standalone web app.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


for router in (
    imports_router,
    economics_router,
    client_quotes_router,
    backup_router,
    system_router,
    home_assistant_router,
):
    app.include_router(router)
