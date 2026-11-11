from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str
    cookie_secure: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]


settings = Settings()
