import argparse
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal, engine
from app.enums import StaffRole
from app.models import StaffUsers
from app.schemas import StaffCreate
from services.staff import create_staff


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", required=True)
    args = parser.parse_args()
    password = getpass("Password (12-128 characters): ")
    if password != getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    try:
        data = StaffCreate(login=args.login.strip().lower(), password=password, role=StaffRole.SUPERADMIN)
    except ValidationError:
        raise SystemExit("Use a 3-50 character login (a-z, 0-9, _, ., -) and a 12-128 character password.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(StaffUsers.id).where(StaffUsers.is_active.is_(True), StaffUsers.role == StaffRole.SUPERADMIN)):
            raise SystemExit("An active superadmin already exists. Add staff through the admin panel.")
        try:
            create_staff(db, data)
        except IntegrityError:
            db.rollback()
            raise SystemExit("This login already exists.")
    print("Superadmin created.")


if __name__ == "__main__":
    main()
