from typing import Annotated
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ThreatEnum
from app.config import settings
from app.models import ClassificationHistory
from app.schemas import MobileStatus
from app.security import get_db
from repository.clients import find_city

router = APIRouter(tags=["mobile"])


@router.get("/status", response_model=MobileStatus)
def get_status(
    db: Annotated[Session, Depends(get_db)],
    city: Annotated[str, Query(min_length=1, max_length=25, pattern=r"^[a-z][a-z0-9_-]*$")] = "dnipro",
):
    record = find_city(db, city)
    if record is None:
        raise HTTPException(404, "Unknown city")
    active = record.threat != ThreatEnum.CALM
    known = record.confirmed
    if known:
        confirmed_id = int(record.event_id.rsplit(":", 1)[-1])
        pending = db.scalar(select(ClassificationHistory.id).where(
            ClassificationHistory.city_id == record.id,
            (
                (ClassificationHistory.status == "pending")
                | (
                    (ClassificationHistory.status == "failed")
                    & (ClassificationHistory.source_message_id > confirmed_id)
                )
            ),
        ).limit(1))
        known = pending is None
    return MobileStatus(
        city=record.code, is_active=active, threat=record.threat,
        version=int(record.event_id.rsplit(":", 1)[-1]) if record.event_id else 0,
        event_id=record.event_id, occurred_at=record.event_at,
        expires_at=record.event_at + timedelta(seconds=settings.alert_ttl_seconds) if record.event_at else None,
        known=known, summary=record.summary, verified_at=record.listener_seen_at if known else None,
    )
