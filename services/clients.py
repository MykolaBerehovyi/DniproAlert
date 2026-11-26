from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Clients
from repository import clients


class UnknownCity(Exception):
    pass


def register_client(db: Session, token: str, city_code: str):
    city = clients.find_city(db, city_code)
    if city is None:
        raise UnknownCity
    token_owner = clients.find_token(db, token)
    if token_owner is None:
        client = Clients(fcm_token=token, city_id=city.id)
        db.add(client)
    else:
        client = token_owner
        client.city_id = city.id
    client.is_active = True
    client.last_seen_at = datetime.now(timezone.utc)
    client.deactivated_at = None
    return client
