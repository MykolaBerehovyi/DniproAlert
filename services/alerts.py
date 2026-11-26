import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.config import settings
from app.enums import ThreatEnum
from app.models import Cities, ClassificationHistory, Clients
from integrations.firebase import InvalidRegistration, send_alert
from repository.clients import find_city
from services.classifier import Classification

logger = logging.getLogger(__name__)
CITY_CODE = "dnipro"
POLL_BATCH = 100
MESSAGE_LIMIT = 4096
MESSAGES = {
    ThreatEnum.CALM: "Відбій повітряної тривоги",
    ThreatEnum.RED_LEVEL: "Червоний рівень загрози",
    ThreatEnum.DRONES: "Загроза ударних БпЛА",
    ThreatEnum.BALLISTICS: "Балістична загроза",
    ThreatEnum.COMBINED: "Комбінована атака",
}


def utc_now():
    return datetime.now(timezone.utc)


def clean_text(value: str) -> str:
    return " ".join(re.sub(r"https?://t\.me/\S+", "", value).split())


def push_payload(city, event_id, version, threat, summary, occurred_at, expires_at):
    return {
        "type": "alert",
        "schema_version": "2",
        "city": city,
        "event_id": event_id,
        "version": str(version),
        "threat": threat.value,
        "message": MESSAGES[threat],
        "summary": summary,
        "occurred_at": occurred_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


class AlertService:
    def __init__(self, sessions, clock=utc_now, send=send_alert):
        self.sessions = sessions
        self.clock = clock
        self.send = send
        self.ttl = timedelta(seconds=settings.alert_ttl_seconds)

    def enabled(self):
        with self.sessions() as db:
            city = find_city(db, CITY_CODE)
            return bool(city and city.monitoring_enabled)

    def _city(self, db):
        return db.scalar(select(Cities).where(Cities.code == CITY_CODE).with_for_update())

    def disconnected(self):
        with self.sessions.begin() as db:
            city = self._city(db)
            if city:
                city.listener_seen_at = None

    def start_source(self, chat_id, latest_id):
        with self.sessions.begin() as db:
            city = self._city(db)
            if city is None or not city.monitoring_enabled:
                return False
            if city.source_chat_id is not None and city.source_chat_id != chat_id:
                raise ValueError("Telegram source does not match stored checkpoint")
            if latest_id > city.last_message_id:
                city.context = []
                db.execute(update(ClassificationHistory).where(
                    ClassificationHistory.city_id == city.id,
                    ClassificationHistory.status == "pending",
                ).values(status="skipped"))
            city.last_message_id = max(city.last_message_id, latest_id)
            city.source_chat_id = chat_id
            city.listener_seen_at = self.clock()
            return True

    def cursor(self):
        with self.sessions() as db:
            city = find_city(db, CITY_CODE)
            return city.last_message_id if city and city.monitoring_enabled else None

    def ingest(self, chat_id, messages, caught_up=True):
        with self.sessions.begin() as db:
            city = self._city(db)
            if city is None or not city.monitoring_enabled or city.source_chat_id != chat_id:
                return False
            now = self.clock()
            for message in sorted(messages, key=lambda message: message.id):
                if message.id <= city.last_message_id:
                    continue
                city.last_message_id = message.id
                body = clean_text(message.text)
                if not body:
                    continue
                invalid = len(body) > MESSAGE_LIMIT or message.at > now + timedelta(minutes=1)
                expired = message.at + self.ttl <= now
                db.add(ClassificationHistory(
                    city_id=city.id, source_chat_id=chat_id, source_message_id=message.id,
                    telegram_message=body[:MESSAGE_LIMIT], occurred_at=message.at,
                    status="failed" if invalid or expired else "pending",
                    error="invalid message" if invalid else "expired" if expired else None,
                ))
            city.listener_seen_at = now if caught_up else None
            return True

    def next_message(self):
        with self.sessions.begin() as db:
            city = self._city(db)
            if city is None or not city.monitoring_enabled:
                return None
            now = self.clock()
            db.execute(update(ClassificationHistory).where(
                ClassificationHistory.city_id == city.id,
                ClassificationHistory.status == "pending",
                ClassificationHistory.occurred_at <= now - self.ttl,
            ).values(status="failed", error="expired"))
            row = db.scalar(select(ClassificationHistory).where(
                ClassificationHistory.city_id == city.id,
                ClassificationHistory.status == "pending",
            ).order_by(ClassificationHistory.source_message_id).limit(1))
            if row is None or (row.next_attempt_at and row.next_attempt_at > now):
                return None
            return row.id, row.telegram_message, city.context, city.threat

    def finish(self, row_id: int, decision: Classification):
        recipients = []
        payload = None
        expires_at = None
        with self.sessions.begin() as db:
            city = self._city(db)
            row = db.get(ClassificationHistory, row_id)
            if not city or not city.monitoring_enabled or not row or row.status != "pending":
                return False
            row.first_answer = decision.preliminary
            row.final_answer = decision.final
            expires_at = row.occurred_at + self.ttl
            if expires_at <= self.clock():
                row.status, row.error = "failed", "expired"
                return False
            row.status, row.threat, row.error = "done", decision.threat, None
            context_item = {"id": row.source_message_id, "text": row.telegram_message, "at": row.occurred_at.isoformat()}
            city.context = (city.context + [context_item])[-20:]
            if row.threat is None:
                return True
            city.threat = row.threat
            event_version = row.source_message_id
            city.event_id = f"{row.source_chat_id}:{row.source_message_id}"
            city.event_at = row.occurred_at
            city.summary = row.telegram_message[:160]
            if row.threat == ThreatEnum.CALM:
                city.context = []
            payload = push_payload(
                city.code, city.event_id, event_version, city.threat, city.summary,
                city.event_at, expires_at,
            )
            recipients = db.execute(select(Clients.id, Clients.fcm_token).where(
                Clients.city_id == city.id, Clients.is_active.is_(True),
            )).all()
        for client_id, token in recipients:
            remaining = (expires_at - self.clock()).total_seconds()
            if remaining <= 0:
                break
            try:
                self.send(token, payload, int(remaining))
            except InvalidRegistration:
                with self.sessions.begin() as db:
                    db.execute(update(Clients).where(
                        Clients.id == client_id,
                        Clients.fcm_token == token,
                        Clients.is_active.is_(True),
                    ).values(is_active=False, deactivated_at=self.clock()))
            except Exception as error:
                logger.warning(
                    "FCM delivery failed message=%s error=%s",
                    row_id,
                    type(error).__name__,
                )
        return True

    def retry(self, row_id: int, error: Exception):
        with self.sessions.begin() as db:
            city = self._city(db)
            row = db.get(ClassificationHistory, row_id)
            if not city or not row or row.status != "pending":
                return
            row.error = type(error).__name__
            row.attempts += 1
            row.next_attempt_at = self.clock() + timedelta(seconds=min(60, 2 ** min(row.attempts, 6)))
            if row.next_attempt_at >= row.occurred_at + self.ttl:
                row.status = "failed"
            logger.warning("Classification error message=%s attempt=%s error=%s", row.source_message_id, row.attempts, row.error)
