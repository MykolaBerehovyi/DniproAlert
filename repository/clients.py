from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cities, Clients


def find_city(db: Session, code: str):
    return db.scalar(select(Cities).where(Cities.code == code))


def find_token(db: Session, token: str):
    return db.scalar(select(Clients).where(Clients.fcm_token == token).with_for_update())


