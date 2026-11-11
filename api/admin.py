import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Cities, StaffSessions
from app.schemas import CityCreate, CityRead, CityUpdate, ClassificationHistoryRead, StaffCreate, StaffRead, StaffUpdate
from app.security import AuthContext, current_auth, get_db, require_superadmin, verify_csrf
from repository import admin as repository
from services import staff as service

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[AuthContext, Depends(current_auth)]
Superadmin = Annotated[AuthContext, Depends(require_superadmin)]


async def read_form(request: Request):
    form = await request.form(max_fields=12, max_files=0)
    if len(form.multi_items()) != len(form) or any(not isinstance(value, str) for value in form.values()):
        raise HTTPException(422, "Некоректна форма.")
    if any(len(value) > 8192 for value in form.values()):
        raise HTTPException(422, "Завелике значення поля.")
    return dict(form)


FormData = Annotated[dict, Depends(read_form)]


def history_city(city_id: str | None = None):
    if city_id in (None, ""):
        return None
    try:
        value = int(city_id)
    except ValueError:
        raise HTTPException(422, "Некоректне місто.")
    if not 1 <= value <= 2147483647:
        raise HTTPException(422, "Некоректне місто.")
    return value


CityFilter = Annotated[int | None, Depends(history_city)]


def render(request: Request, template: str, auth: AuthContext | None = None, status_code: int = 200, **context):
    context = {
        "current_user": auth.user if auth else None,
        "csrf_token": auth.session.csrf_token if auth else "",
        "errors": {},
        "form": {},
        "notice": None,
        **context,
    }
    return request.app.state.templates.TemplateResponse(
        request=request, name=template, context=context, status_code=status_code
    )


def validation_errors(error: ValidationError):
    return {str(item["loc"][0]): "Перевірте значення та довжину поля." for item in error.errors()}


def checked_fields(request: Request, form: dict, auth: AuthContext):
    fields = dict(form)
    verify_csrf(request, fields.pop("csrf_token", ""), auth.session.csrf_token)
    return fields


@router.get("/admin/login", include_in_schema=False)
def login_page(request: Request, db: Db):
    if service.find_session(db, request.cookies.get("admin_session")):
        return RedirectResponse("/admin/cities", status_code=303)
    token = secrets.token_urlsafe(32)
    response = render(request, "login.html", error=None, csrf_token=token)
    response.set_cookie("login_csrf", token, max_age=1800, httponly=True, secure=settings.cookie_secure, samesite="strict")
    return response


@router.post("/admin/login", include_in_schema=False)
def login(request: Request, form: FormData, db: Db):
    verify_csrf(request, form.get("csrf_token", ""), request.cookies.get("login_csrf"))
    if set(form) != {"login", "password", "csrf_token"}:
        raise HTTPException(422, "Некоректна форма.")
    if not request.app.state.login_limiter.allow(request.client.host if request.client else "unknown"):
        return render(request, "login.html", status_code=429, error="Забагато спроб. Спробуйте через 5 хвилин.", csrf_token=form["csrf_token"])
    user = service.authenticate(db, form["login"][:50], form["password"])
    if user is None or len(form["login"]) > 50:
        return render(request, "login.html", status_code=401, error="Невірний логін або пароль.", csrf_token=form["csrf_token"])
    token = service.create_session(db, user, request.cookies.get("admin_session"))
    response = RedirectResponse("/admin/cities", status_code=303)
    response.set_cookie(
        "admin_session", token, max_age=settings.session_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="strict",
    )
    response.delete_cookie("login_csrf")
    return response


@router.post("/admin/logout", include_in_schema=False)
def logout(request: Request, form: FormData, db: Db, auth: Auth):
    fields = checked_fields(request, form, auth)
    if fields:
        raise HTTPException(422, "Некоректна форма.")
    db.execute(delete(StaffSessions).where(StaffSessions.id == auth.session.id))
    db.commit()
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    return response


@router.get("/admin", include_in_schema=False)
def admin_home(auth: Auth):
    return RedirectResponse("/admin/cities", status_code=303)


@router.get("/admin/cities", include_in_schema=False)
def cities_page(request: Request, db: Db, auth: Auth, saved: bool = False):
    return render(request, "cities.html", auth, cities=repository.list_cities(db), notice="Місто збережено." if saved else None)


@router.post("/admin/cities", include_in_schema=False)
def create_city(request: Request, form: FormData, db: Db, auth: Auth):
    fields = checked_fields(request, form, auth)
    try:
        data = CityCreate.model_validate(fields)
    except ValidationError as error:
        return render(request, "cities.html", auth, status_code=422, cities=repository.list_cities(db), form=fields, errors=validation_errors(error))
    try:
        repository.add_city(db, data.code, data.name)
    except IntegrityError:
        db.rollback()
        return render(request, "cities.html", auth, status_code=409, cities=repository.list_cities(db), form=fields, errors={"code": "Місто з таким кодом уже існує."})
    return RedirectResponse("/admin/cities?saved=true", status_code=303)


@router.get("/admin/cities/{city_id}/edit", include_in_schema=False)
def city_edit_page(city_id: int, request: Request, db: Db, auth: Auth):
    city = db.get(Cities, city_id)
    if city is None:
        raise HTTPException(404, "Місто не знайдено.")
    return render(request, "city_edit.html", auth, city=city, form={"name": city.name})


@router.post("/admin/cities/{city_id}/edit", include_in_schema=False)
def edit_city(city_id: int, request: Request, form: FormData, db: Db, auth: Auth):
    fields = checked_fields(request, form, auth)
    city = db.get(Cities, city_id)
    if city is None:
        raise HTTPException(404, "Місто не знайдено.")
    try:
        data = CityUpdate.model_validate(fields)
    except ValidationError as error:
        return render(request, "city_edit.html", auth, status_code=422, city=city, form=fields, errors=validation_errors(error))
    repository.rename_city(db, city, data.name)
    return RedirectResponse("/admin/cities?saved=true", status_code=303)


@router.get("/admin/history", include_in_schema=False)
def history_page(request: Request, db: Db, auth: Auth, city_id: CityFilter, page: Annotated[int, Query(ge=1, le=100000)] = 1):
    history, has_next = repository.list_history(db, city_id, page)
    return render(request, "history.html", auth, history=history, cities=repository.list_cities(db), selected_city=city_id, page=page, has_next=has_next)


@router.get("/admin/staff", include_in_schema=False)
def staff_page(request: Request, db: Db, auth: Superadmin, saved: bool = False):
    return render(request, "staff.html", auth, staff=repository.list_staff(db), notice="Доступи збережено." if saved else None)


@router.post("/admin/staff", include_in_schema=False)
def create_staff(request: Request, form: FormData, db: Db, auth: Superadmin):
    fields = checked_fields(request, form, auth)
    fields["login"] = fields.get("login", "").strip().lower()
    safe_form = {key: value for key, value in fields.items() if key != "password"}
    try:
        data = StaffCreate.model_validate(fields)
    except ValidationError as error:
        return render(request, "staff.html", auth, status_code=422, staff=repository.list_staff(db), form=safe_form, errors=validation_errors(error))
    try:
        service.create_staff(db, data)
    except IntegrityError:
        db.rollback()
        return render(request, "staff.html", auth, status_code=409, staff=repository.list_staff(db), form=safe_form, errors={"login": "Цей логін уже зайнятий."})
    return RedirectResponse("/admin/staff?saved=true", status_code=303)


@router.post("/admin/staff/{user_id}/update", include_in_schema=False)
def edit_staff(user_id: int, request: Request, form: FormData, db: Db, auth: Superadmin):
    fields = checked_fields(request, form, auth)
    if "is_active" in fields and fields["is_active"] not in {"on", "true", "1"}:
        raise HTTPException(422, "Некоректний статус доступу.")
    fields["is_active"] = "is_active" in fields
    try:
        data = StaffUpdate.model_validate(fields)
    except ValidationError:
        raise HTTPException(422, "Перевірте роль і статус доступу.")
    try:
        service.update_staff(db, auth.user.id, user_id, data)
    except PermissionError as error:
        db.rollback()
        raise HTTPException(403, str(error))
    except LookupError as error:
        db.rollback()
        raise HTTPException(404, str(error))
    except ValueError as error:
        db.rollback()
        return render(request, "staff.html", auth, status_code=409, staff=repository.list_staff(db), errors={"general": str(error)})
    return RedirectResponse("/admin/staff?saved=true", status_code=303)


@router.get("/api/cities", response_model=list[CityRead])
def cities_api(db: Db, auth: Auth):
    return repository.list_cities(db)


@router.get("/api/history", response_model=list[ClassificationHistoryRead])
def history_api(db: Db, auth: Auth, city_id: CityFilter, page: Annotated[int, Query(ge=1, le=100000)] = 1):
    history, _ = repository.list_history(db, city_id, page)
    return history


@router.get("/api/staff", response_model=list[StaffRead])
def staff_api(db: Db, auth: Superadmin):
    return repository.list_staff(db)
