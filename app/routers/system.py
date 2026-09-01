from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import main as core
from ..db import get_db
from ..diagnostics import build_system_check
from ..settings import get_settings

router = APIRouter()


@router.get("/system", response_class=HTMLResponse)
def system_check_page(request: Request, db: Session = Depends(get_db)):
    report = build_system_check(get_settings(db))
    return core.templates.TemplateResponse(
        request,
        "system_check.html",
        core.ctx(request, report=report),
    )


@router.get("/api/system-check")
def system_check_api(db: Session = Depends(get_db)):
    return build_system_check(get_settings(db))
