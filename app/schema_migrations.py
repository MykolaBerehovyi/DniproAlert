from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config import ROOT
from app.database import engine


def upgrade_database(bind=engine):
    config = Config(str(ROOT / "alembic.ini"))
    with bind.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(70806420)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
