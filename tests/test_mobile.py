import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import settings
from app.main import create_app
from app.models import Cities, ClassificationHistory, Clients
from app.schema_migrations import upgrade_database
from integrations.firebase import InvalidRegistration, send_alert
from integrations.telegram import IncomingMessage
from services.alerts import AlertService
from services.classifier import Classification, classify
from services.retention import run_retention


class MobileTests(unittest.TestCase):
    def setUp(self):
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            self.skipTest("Set TEST_DATABASE_URL")
        self.schema = "mobile_test_" + uuid4().hex
        self.admin_engine = create_engine(url)
        self.addCleanup(self.admin_engine.dispose)
        with self.admin_engine.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.addCleanup(self.drop_schema)
        engine = create_engine(url, connect_args={"options": f"-csearch_path={self.schema}"})
        self.addCleanup(engine.dispose)
        upgrade_database(engine)
        self.sessions = sessionmaker(engine)
        self.api = TestClient(create_app(self.sessions, initialize_db=False))
        self.addCleanup(self.api.close)
        self.now = datetime.now(timezone.utc)
        self.sent = []
        self.alerts = AlertService(
            self.sessions,
            clock=lambda: self.now,
            send=lambda *args: self.sent.append(args),
        )

    def drop_schema(self):
        with self.admin_engine.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))

    def register(self, token, city="dnipro", **extra):
        with patch.object(settings, "app_check_allowed_app_ids", "test-app"), patch(
            "integrations.firebase.verify_attestation", return_value="test-app"
        ):
            return self.api.post(
                "/clients/register",
                headers={"X-Firebase-AppCheck": "fake"},
                json={"fcm_token": token, "city": city, **extra},
            )

    def test_registration_has_no_remote_preferences(self):
        self.assertEqual(self.register("token").status_code, 200)
        self.assertEqual(self.register("replacement").status_code, 200)
        self.assertEqual(self.register("replacement").status_code, 200)
        self.assertEqual(self.register("replacement", notifications_enabled=False).status_code, 422)
        with self.sessions() as db:
            tokens = set(db.scalars(select(Clients.fcm_token)))
            self.assertEqual(tokens, {"token", "replacement"})

    def test_final_decision_city_delivery_and_retention(self):
        self.assertEqual(self.register("first").status_code, 200)
        with self.sessions.begin() as db:
            db.scalar(select(Cities).where(Cities.code == "dnipro")).monitoring_enabled = True
            db.add(Cities(code="kyiv", name="Київ"))
        self.assertEqual(self.register("other-city", city="kyiv").status_code, 200)
        self.assertTrue(self.alerts.start_source(-10042, 7))
        self.assertFalse(self.api.get("/status").json()["known"])
        incoming = IncomingMessage(8, self.now, "Synthetic exercise")
        self.alerts.ingest(-10042, [incoming, incoming])
        self.assertTrue(self.alerts.finish(self.alerts.next_message()[0], Classification("Ні", "Так: балістика")))
        status = self.api.get("/status?city=dnipro").json()
        self.assertTrue(status["known"])
        self.assertEqual((status["threat"], status["version"]), ("ballistics", 8))
        self.assertEqual(len(self.sent), 1)
        token, payload, ttl = self.sent[0]
        self.assertEqual(token, "first")
        self.assertEqual(payload["event_id"], "-10042:8")
        self.assertEqual(payload["schema_version"], "2")
        self.assertGreater(ttl, 0)
        self.alerts.ingest(-10042, [IncomingMessage(9, self.now, "Ignore test")])
        self.alerts.finish(self.alerts.next_message()[0], Classification("Відбій", "Ні"))
        self.assertEqual(self.api.get("/status").json()["version"], 8)

        def reject(*args):
            raise InvalidRegistration

        self.alerts.send = reject
        self.alerts.ingest(-10042, [IncomingMessage(10, self.now, "Clear test")])
        self.alerts.finish(self.alerts.next_message()[0], Classification("Ні", "Відбій"))
        self.assertEqual(self.api.get("/status").json()["threat"], "calm")
        with self.sessions() as db:
            self.assertFalse(db.scalar(select(Clients).where(Clients.fcm_token == "first")).is_active)
            self.assertEqual(db.scalar(select(func.count()).select_from(ClassificationHistory)), 3)
        counts = run_retention(self.sessions, self.now + timedelta(days=31))
        self.assertEqual(counts["clients"], 1)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(Clients)).fcm_token, "other-city")

    def test_restart_does_not_replay_an_already_processed_event(self):
        self.assertEqual(self.register("first").status_code, 200)
        with self.sessions.begin() as db:
            db.scalar(select(Cities)).monitoring_enabled = True
        self.alerts.start_source(-10042, 7)
        self.alerts.ingest(-10042, [IncomingMessage(8, self.now, "Synthetic exercise")])
        self.alerts.finish(self.alerts.next_message()[0], Classification("Ні", "Так: шахеди"))
        self.alerts.start_source(-10042, 9)
        self.assertTrue(self.api.get("/status").json()["known"])
        self.assertEqual(len(self.sent), 1)


class ClassifierTests(unittest.TestCase):
    def test_verifier_is_called_even_when_preliminary_says_ignore(self):
        from app.enums import ThreatEnum

        create = AsyncMock(side_effect=[
            SimpleNamespace(output_text="Ні"), SimpleNamespace(output_text="Так: шахеди"),
        ])
        result = asyncio.run(classify(
            SimpleNamespace(responses=SimpleNamespace(create=create)),
            "Synthetic exercise", [], ThreatEnum.CALM, "primary", "verifier",
        ))
        self.assertEqual(result.threat, ThreatEnum.DRONES)
        self.assertEqual(create.await_args_list[1].kwargs["model"], "verifier")


class FirebaseTests(unittest.TestCase):
    def test_message_is_rendered_by_the_app(self):
        payload = {"type": "alert", "city": "dnipro", "schema_version": "2"}
        with patch("integrations.firebase.firebase_app"), patch(
            "integrations.firebase.messaging.send", return_value="accepted"
        ) as send:
            self.assertEqual(send_alert("test-token", payload, 60), "accepted")
        message = send.call_args.args[0]
        self.assertEqual(message.data, payload)
        self.assertIsNone(message.notification)
        self.assertIsNone(message.android.notification)
        self.assertEqual(message.android.ttl, timedelta(seconds=60))
