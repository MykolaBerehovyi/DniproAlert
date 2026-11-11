import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import StaffRole
from app.models import StaffSessions, StaffUsers
from app.schemas import StaffCreate, StaffUpdate

password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(24))


class LoginLimiter:
    def __init__(self):
        self.attempts = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, address: str):
        now = time.monotonic()
        with self.lock:
            recent = [value for value in self.attempts.pop(address, []) if now - value < 300]
            self.attempts[address] = recent
            while len(self.attempts) > 4096:
                self.attempts.popitem(last=False)
            if len(recent) >= 10:
                return False
            recent.append(now)
            return True


def hash_token(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, login: str, password: str):
    user = db.scalar(select(StaffUsers).where(StaffUsers.login == login.strip().lower()))
    candidate = user.password_hash if user else dummy_hash
    if not 1 <= len(password) <= 128:
        return None
    if not password_hasher.verify(password, candidate):
        return None
    return user if user and user.is_active else None


def create_session(db: Session, user: StaffUsers, previous_token: str | None = None):
    now = datetime.now(timezone.utc)
    db.execute(delete(StaffSessions).where(StaffSessions.expires_at <= now))
    if previous_token:
        db.execute(delete(StaffSessions).where(StaffSessions.token_hash == hash_token(previous_token)))
    token = secrets.token_urlsafe(32)
    session = StaffSessions(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    db.commit()
    return token


def find_session(db: Session, token: str | None):
    if not token or len(token) > 128:
        return None
    row = db.execute(
        select(StaffSessions, StaffUsers)
        .join(StaffUsers, StaffUsers.id == StaffSessions.user_id)
        .where(
            StaffSessions.token_hash == hash_token(token),
            StaffSessions.expires_at > datetime.now(timezone.utc),
            StaffUsers.is_active.is_(True),
        )
    ).first()
    return row


def create_staff(db: Session, data: StaffCreate):
    user = StaffUsers(
        login=data.login,
        password_hash=password_hasher.hash(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_staff(db: Session, actor_id: int, target_id: int, data: StaffUpdate):
    users = db.scalars(select(StaffUsers).order_by(StaffUsers.id).with_for_update().execution_options(populate_existing=True)).all()
    actor = next((user for user in users if user.id == actor_id), None)
    target = next((user for user in users if user.id == target_id), None)
    if not actor or not actor.is_active or actor.role != StaffRole.SUPERADMIN:
        raise PermissionError("Недостатньо прав.")
    if target is None:
        raise LookupError("Співробітника не знайдено.")
    removes_superadmin = target.role == StaffRole.SUPERADMIN and target.is_active and (
        data.role != StaffRole.SUPERADMIN or not data.is_active
    )
    if removes_superadmin:
        active_superadmins = sum(user.is_active and user.role == StaffRole.SUPERADMIN for user in users)
        if active_superadmins <= 1:
            raise ValueError("Не можна вимкнути або понизити останнього суперадміністратора.")
    if target.id == actor.id and (not data.is_active or data.role != StaffRole.SUPERADMIN):
        raise ValueError("Не можна забрати власний доступ. Зверніться до іншого суперадміністратора.")
    target.role = data.role
    target.is_active = data.is_active
    if not target.is_active:
        db.execute(delete(StaffSessions).where(StaffSessions.user_id == target.id))
    db.commit()
    return target
