from openai import AsyncOpenAI

from app.config import settings


def open_client():
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required")
    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=20, max_retries=0)
