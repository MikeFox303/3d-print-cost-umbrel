from __future__ import annotations

from . import main as core
from .routers.backup import router as backup_router
from .routers.client_quotes import router as client_quotes_router
from .routers.economics import router as economics_router
from .routers.home_assistant import router as home_assistant_router
from .routers.imports import router as imports_router
from .routers.system import router as system_router

app = core.app
_validate_quote_inputs = core._validate_quote_inputs

for router in (
    imports_router,
    economics_router,
    client_quotes_router,
    backup_router,
    system_router,
    home_assistant_router,
):
    app.include_router(router)
