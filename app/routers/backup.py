from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from .. import main as core
from ..backup_restore import (
    MAX_BACKUP_BYTES,
    BackupValidationError,
    apply_restore,
    validate_backup,
)
from ..db import get_db

router = APIRouter()


@router.get("/backup/restore", response_class=HTMLResponse)
def backup_restore_page(request: Request):
    return core.templates.TemplateResponse(request, "backup_restore.html", core.ctx(request))


async def _read_backup_upload(file: UploadFile) -> bytes:
    raw = await file.read(MAX_BACKUP_BYTES + 1)
    if len(raw) > MAX_BACKUP_BYTES:
        raise BackupValidationError("Backup больше 25 MiB; восстановление остановлено для безопасности.")
    return raw


@router.post("/api/backup/restore/preview")
async def backup_restore_preview(file: UploadFile = File(...)):
    try:
        raw = await _read_backup_upload(file)
        plan = validate_backup(raw)
        return plan.to_dict()
    except BackupValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        await file.close()


@router.post("/api/backup/restore/apply")
async def backup_restore_apply(
    file: UploadFile = File(...),
    confirmation_token: str = Form(...),
    confirmation_phrase: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        if confirmation_phrase != "RESTORE":
            raise BackupValidationError("Для восстановления требуется точная фраза RESTORE.")
        raw = await _read_backup_upload(file)
        plan = validate_backup(raw)
        return apply_restore(db, plan, confirmation_token)
    except BackupValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        db.rollback()
        return JSONResponse(
            {"error": "Восстановление не выполнено: транзакция отменена, исходные данные сохранены."},
            status_code=500,
        )
    finally:
        await file.close()
