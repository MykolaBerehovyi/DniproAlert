import asyncio
import logging

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.schema_migrations import upgrade_database
from integrations.ai import open_client
from integrations.telegram import TelegramSource
from services.alerts import AlertService, POLL_BATCH
from services.classifier import classify
from services.retention import run_retention

logger = logging.getLogger(__name__)


async def read_source(source, alerts):
    while True:
        cursor = await asyncio.to_thread(alerts.cursor)
        if cursor is None:
            return
        messages = await asyncio.wait_for(source.read_after(cursor, POLL_BATCH), timeout=15)
        caught_up = len(messages) < POLL_BATCH
        if not await asyncio.to_thread(alerts.ingest, source.chat_id, messages, caught_up):
            return
        if caught_up:
            await source.wait_for_update()


async def process_messages(alerts, client):
    while True:
        item = await asyncio.to_thread(alerts.next_message)
        if item is None:
            await asyncio.sleep(1)
            continue
        row_id, body, context, current = item
        try:
            result = await classify(client, body, context, current,
                                    settings.openai_classifier_model, settings.openai_verifier_model)
        except Exception as error:
            await asyncio.to_thread(alerts.retry, row_id, error)
        else:
            await asyncio.to_thread(alerts.finish, row_id, result)


async def listen(alerts):
    while True:
        if not await asyncio.to_thread(alerts.enabled):
            await asyncio.sleep(5)
            continue
        source = None
        try:
            source = TelegramSource()
            await asyncio.wait_for(source.connect(), timeout=20)
            latest = await asyncio.wait_for(source.latest_id(), timeout=15)
            async with open_client() as client:
                if not await asyncio.to_thread(alerts.start_source, source.chat_id, latest):
                    continue
                reader = asyncio.create_task(read_source(source, alerts))
                processor = asyncio.create_task(process_messages(alerts, client))
                try:
                    done, _ = await asyncio.wait((reader, processor), return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    reader.cancel()
                    processor.cancel()
                    await asyncio.gather(reader, processor, return_exceptions=True)
        except Exception as error:
            logger.warning("Telegram worker unavailable error=%s", type(error).__name__)
        finally:
            try:
                await asyncio.to_thread(alerts.disconnected)
            finally:
                if source:
                    await source.close()
        await asyncio.sleep(5)


async def retain():
    while True:
        try:
            counts = await asyncio.to_thread(run_retention, SessionLocal)
            logger.info("Retention completed %s", counts)
        except Exception as error:
            logger.warning("Retention failed error=%s", type(error).__name__)
        await asyncio.sleep(settings.retention_interval_hours * 3600)


async def run():
    await asyncio.gather(listen(AlertService(SessionLocal)), retain())


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    upgrade_database()
    with engine.connect() as connection:
        locked = connection.scalar(text("SELECT pg_try_advisory_lock(70806421)"))
        connection.commit()
        if not locked:
            raise SystemExit("Another alert worker is already running")
        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            pass
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(70806421)"))


if __name__ == "__main__":
    main()
