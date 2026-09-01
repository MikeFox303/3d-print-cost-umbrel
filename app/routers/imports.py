from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Filament
from ..three_mf import ThreeMFImportError, import_bambu_3mf, match_local_filaments

router = APIRouter()


@router.post("/api/import/3mf")
async def import_3mf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        file.file.seek(0)
        plates = import_bambu_3mf(file.file, file.filename or "")
        local_filaments = (
            db.query(Filament)
            .filter(Filament.archived.is_(False))
            .order_by(Filament.brand, Filament.name, Filament.id)
            .all()
        )
        payload = []
        for plate in plates:
            plate_data = plate.to_dict()
            for filament in plate_data["filaments"]:
                match = match_local_filaments(
                    filament.get("type"),
                    filament.get("color"),
                    local_filaments,
                )
                filament["local_candidates"] = match["candidates"]
                filament["auto_local_filament_id"] = match["auto_select_id"]
                filament["auto_local_match_reason"] = match["auto_select_reason"]
            payload.append(plate_data)
        return {
            "filename": file.filename or "",
            "source": "bambu_studio_3mf",
            "local_matching": "read_only_local_price_database",
            "plates": payload,
        }
    except ThreeMFImportError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        await file.close()
