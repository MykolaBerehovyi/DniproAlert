import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.enums import StaffRole
from app.models import StaffSessions, StaffUsers
from services.staff import find_session


@dataclass
class AuthContext:
    session: StaffSessions
    user: StaffUsers




def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


def current_auth(request: Request, db: Session = Depends(get_db)):
    row = find_session(db, request.cookies.get("admin_session"))
    if row is None:
        raise HTTPException(401, "Увійдіть до панелі.")
    return AuthContext(session=row[0], user=row[1])


def require_superadmin(auth: AuthContext = Depends(current_auth)):
    if auth.user.role != StaffRole.SUPERADMIN:
        raise HTTPException(403, "Цей розділ доступний лише суперадміністратору.")
    return auth


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            expected = urlsplit(str(request.base_url))
        except ValueError:
            raise HTTPException(403, "Некоректне джерело запиту.")
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
            raise HTTPException(403, "Запит з іншого сайту відхилено.")


def verify_csrf(request: Request, submitted: str, expected: str | None):
    check_origin(request)
    if not expected or not submitted or not secrets.compare_digest(submitted.encode(), expected.encode()):
        raise HTTPException(403, "Форма застаріла. Оновіть сторінку та спробуйте знову.")


class FormSizeLimitMiddleware:
    def __init__(self, app, max_bytes=32768):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": b"Request body is too large."})
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        consumed = False

        async def buffered_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)
