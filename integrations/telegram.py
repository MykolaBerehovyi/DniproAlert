import asyncio
from dataclasses import dataclass
from datetime import datetime

from telethon import TelegramClient, events, utils

from app.config import ROOT, settings


@dataclass(frozen=True)
class IncomingMessage:
    id: int
    at: datetime
    text: str


class TelegramSource:
    def __init__(self):
        if not all((settings.telegram_api_id, settings.telegram_api_hash, settings.telegram_source)):
            raise RuntimeError("Telegram source and API credentials are required")
        path = ROOT / settings.telegram_session_path
        if not path.is_file():
            raise RuntimeError("Authorize the worker's Telegram session first")
        self.client = TelegramClient(
            str(path), settings.telegram_api_id, settings.telegram_api_hash.get_secret_value(),
            request_retries=1, connection_retries=1, flood_sleep_threshold=0,
        )
        self.channel = None
        self.chat_id = None
        self.changed = asyncio.Event()

    async def connect(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized")
        self.channel = await self.client.get_input_entity(settings.telegram_source)
        self.chat_id = utils.get_peer_id(self.channel)
        self.client.add_event_handler(self.channel_changed, events.NewMessage(chats=self.channel))

    async def channel_changed(self, event):
        self.changed.set()

    async def wait_for_update(self):
        try:
            await asyncio.wait_for(self.changed.wait(), timeout=10)
        except TimeoutError:
            pass
        self.changed.clear()

    async def latest_id(self):
        messages = await self.client.get_messages(self.channel, limit=1)
        return messages[0].id if messages else 0

    async def read_after(self, message_id: int, limit: int):
        return [
            IncomingMessage(item.id, item.date, getattr(item, "message", None) or "")
            async for item in self.client.iter_messages(
                self.channel, min_id=message_id, reverse=True, limit=limit,
            )
        ]

    async def close(self):
        await self.client.disconnect()
