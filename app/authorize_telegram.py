import asyncio

from telethon import TelegramClient

from app.config import ROOT, settings


async def authorize():
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
    session = ROOT / settings.telegram_session_path
    if session.suffix != ".session":
        raise SystemExit("TELEGRAM_SESSION_PATH must end in .session")
    client = TelegramClient(
        str(session), settings.telegram_api_id, settings.telegram_api_hash.get_secret_value()
    )
    try:
        await client.start()
        print("Telegram session authorized")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(authorize())
