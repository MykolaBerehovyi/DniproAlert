from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str
    cookie_secure: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    firebase_credentials_path: Path | None = None
    app_check_allowed_app_ids: str = ""
    telegram_api_id: int | None = None
    telegram_api_hash: SecretStr | None = None
    telegram_session_path: Path = ROOT / "telegram.session"
    telegram_source: str | None = None
    openai_api_key: SecretStr | None = None
    openai_classifier_model: str = "gpt-5.4-mini"
    openai_verifier_model: str = "gpt-5.6-luna"
    alert_ttl_seconds: int = Field(default=3600, ge=15, le=3600)
    retention_interval_hours: int = Field(default=12, ge=1)


settings = Settings()
