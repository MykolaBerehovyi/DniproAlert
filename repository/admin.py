from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cities, ClassificationHistory, StaffUsers


def list_cities(db: Session):
    return db.scalars(select(Cities).order_by(Cities.name, Cities.id)).all()


def add_city(db: Session, code: str, name: str):
    city = Cities(code=code, name=name)
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


def rename_city(db: Session, city: Cities, name: str):
    city.name = name
    db.commit()


def list_history(db: Session, city_id: int | None, page: int, page_size: int = 50):
    query = select(ClassificationHistory, Cities.name).join(Cities, Cities.id == ClassificationHistory.city_id)
    if city_id is not None:
        query = query.where(ClassificationHistory.city_id == city_id)
    rows = db.execute(
        query.order_by(ClassificationHistory.occurred_at.desc(), ClassificationHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
    ).all()
    items = []
    for history, city_name in rows[:page_size]:
        item = {column.name: getattr(history, column.name) for column in ClassificationHistory.__table__.columns}
        item["city_name"] = city_name
        item["occurred_at"] = item["occurred_at"].astimezone(timezone.utc)
        item["created_at"] = item["created_at"].astimezone(timezone.utc)
        items.append(item)
    return items, len(rows) > page_size


def list_staff(db: Session):
    return db.scalars(select(StaffUsers).order_by(StaffUsers.id)).all()
