from datetime import timedelta
from functools import lru_cache

import firebase_admin
from firebase_admin import app_check, credentials, messaging

from app.config import ROOT, settings


class FirebaseUnavailable(Exception):
    pass


class InvalidRegistration(Exception):
    pass


@lru_cache(maxsize=1)
def firebase_app():
    path = settings.firebase_credentials_path
    if path is None:
        raise FirebaseUnavailable("Firebase credentials are not configured")
    try:
        return firebase_admin.get_app("mobile-alert")
    except ValueError:
        try:
            return firebase_admin.initialize_app(
                credentials.Certificate(str(ROOT / path)),
                options={"httpTimeout": 10},
                name="mobile-alert",
            )
        except ValueError:
            return firebase_admin.get_app("mobile-alert")


def verify_attestation(token: str) -> str:
    try:
        app = firebase_app()
    except (OSError, ValueError) as error:
        raise FirebaseUnavailable from error
    claims = app_check.verify_token(token, app=app)
    return str(claims.get("sub") or "")


def send_alert(token: str, payload: dict[str, str], ttl_seconds: int) -> str:
    message = messaging.Message(
        token=token,
        data=payload,
        android=messaging.AndroidConfig(
            priority="high",
            ttl=timedelta(seconds=ttl_seconds),
            collapse_key=f"city_alert_{payload['city']}",
        ),
    )
    try:
        return messaging.send(message, app=firebase_app())
    except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as error:
        raise InvalidRegistration from error
