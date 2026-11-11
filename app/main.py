from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.admin import router
from app.config import ROOT, settings
from app.database import Base, SessionLocal
from app.security import FormSizeLimitMiddleware
from services.staff import LoginLimiter


def create_app(session_factory=None, initialize_db=True):
    factory = session_factory or SessionLocal

    @asynccontextmanager
    async def lifespan(application):
        if initialize_db:
            with factory() as db:
                Base.metadata.create_all(bind=db.get_bind())
        yield

    application = FastAPI(title="Dnipro Alert Admin", lifespan=lifespan)
    application.state.session_factory = factory
    application.state.templates = Jinja2Templates(directory=ROOT / "app" / "templates")
    application.state.login_limiter = LoginLimiter()
    application.add_middleware(FormSizeLimitMiddleware)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    application.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
    application.include_router(router)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/admin"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        if request.url.path.startswith(("/admin", "/api")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        if error.status_code == 401:
            return RedirectResponse("/admin/login", status_code=303)
        return application.state.templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"current_user": None, "csrf_token": "", "status_code": error.status_code, "message": error.detail},
            status_code=error.status_code,
        )

    @application.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/admin", status_code=303)

    @application.get("/healthz")
    def health():
        with factory() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "postgresql"}

    return application


app = create_app()
