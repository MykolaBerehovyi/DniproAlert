from datetime import timedelta

from sqlalchemy import and_, delete, or_, select

from app.models import ClassificationHistory, Clients, StaffSessions
from services.alerts import utc_now


def run_retention(sessions, now=None, limit=1000):
    now = now or utc_now()
    tasks = (
        (ClassificationHistory, or_(
            and_(ClassificationHistory.status.in_(["done", "skipped"]), ClassificationHistory.occurred_at < now - timedelta(days=60)),
            and_(ClassificationHistory.status == "failed", ClassificationHistory.occurred_at < now - timedelta(days=90)),
        )),
        (Clients, and_(Clients.is_active.is_(False), Clients.deactivated_at < now - timedelta(days=30))),
        (StaffSessions, StaffSessions.expires_at <= now),
    )
    counts = {}
    with sessions.begin() as db:
        for model, condition in tasks:
            candidates = select(model.id).where(condition).order_by(model.id).limit(limit)
            result = db.execute(delete(model).where(model.id.in_(candidates), condition))
            counts[model.__tablename__] = result.rowcount
    return counts
