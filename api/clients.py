from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import ClientCreate
from app.security import get_db
from integrations import firebase
from services import clients
from services.staff import LoginLimiter

router = APIRouter(prefix="/clients", tags=["mobile"])
registration_limit = LoginLimiter(limit=40, window_seconds=60)


@router.post("/register")
def register(
    data: ClientCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    app_check: Annotated[str, Header(alias="X-Firebase-AppCheck")] = "",
):
    if not registration_limit.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "Too many registration attempts")
    if not app_check or len(app_check) > 8192:
        raise HTTPException(401, "App attestation required")
    try:
        app_id = firebase.verify_attestation(app_check)
    except firebase.FirebaseUnavailable:
        raise HTTPException(503, "App attestation temporarily unavailable") from None
    except Exception:
        raise HTTPException(401, "Invalid app attestation") from None
    allowed = {value.strip() for value in settings.app_check_allowed_app_ids.split(",") if value.strip()}
    if not app_id or app_id not in allowed:
        raise HTTPException(403, "App is not allowed")
    try:
        clients.register_client(db, data.fcm_token, data.city)
        db.commit()
    except clients.UnknownCity:
        raise HTTPException(404, "Unknown city") from None
    except IntegrityError:
        raise HTTPException(409, "FCM token already exists") from None
    return {"message": "ok"}
