import hashlib
import os
import re
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema


class HiddenInputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("type") == "hidden":
            self.values[attributes.get("name")] = attributes.get("value", "")


class AdminTests(unittest.TestCase):
    password = "Correct-Horse-42!"

    @classmethod
    def setUpClass(cls):
        raw_url = os.environ.get("TEST_DATABASE_URL")
        if not raw_url:
            raise unittest.SkipTest("Set TEST_DATABASE_URL to an isolated PostgreSQL database")
        url = make_url(raw_url)
        if url.get_backend_name() != "postgresql":
            raise RuntimeError("TEST_DATABASE_URL must use PostgreSQL")
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        from app.database import Base
        from app.enums import StaffRole, ThreatEnum
        from app.main import create_app
        from app.models import Cities, ClassificationHistory, StaffSessions, StaffUsers

        cls.url = url
        cls.Base = Base
        cls.StaffRole = StaffRole
        cls.ThreatEnum = ThreatEnum
        cls.Cities = Cities
        cls.ClassificationHistory = ClassificationHistory
        cls.StaffSessions = StaffSessions
        cls.StaffUsers = StaffUsers
        cls.create_app = staticmethod(create_app)
        cls.password_hash = PasswordHash.recommended().hash(cls.password)

    def setUp(self):
        self.schema = "admin_test_" + uuid.uuid4().hex
        self.owns_schema = False
        self.engine = None
        self.client = None
        self.other_clients = []
        self.admin_engine = create_engine(self.url)
        self.addCleanup(self.cleanup_schema)
        with self.admin_engine.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.owns_schema = True
        self.engine = create_engine(
            self.url, connect_args={"options": "-csearch_path=" + self.schema}
        )
        self.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            city = self.Cities(
                code="dnipro", name="Dnipro", threat=self.ThreatEnum.CALM
            )
            owner = self.StaffUsers(
                login="owner", password_hash=self.password_hash,
                role=self.StaffRole.SUPERADMIN, is_active=True,
            )
            operator = self.StaffUsers(
                login="operator", password_hash=self.password_hash,
                role=self.StaffRole.ADMIN, is_active=True,
            )
            session.add_all([city, owner, operator])
            session.flush()
            self.city_id = city.id
            self.owner_id = owner.id
            self.operator_id = operator.id
        self.app = self.create_app(session_factory=self.sessions, initialize_db=False)
        self.client = TestClient(self.app, follow_redirects=False)
        self.client.__enter__()

    def cleanup_schema(self):
        for client in self.other_clients:
            client.__exit__(None, None, None)
        if self.client is not None:
            self.client.__exit__(None, None, None)
        if self.engine is not None:
            self.engine.dispose()
        if self.owns_schema:
            if not re.fullmatch(r"admin_test_[0-9a-f]{32}", self.schema):
                raise RuntimeError("Refusing to drop a schema not owned by this test")
            with self.admin_engine.begin() as connection:
                connection.execute(DropSchema(self.schema, cascade=True))
            self.owns_schema = False
        self.admin_engine.dispose()

    def token(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        value = HiddenInputs(response.text).values.get("csrf_token")
        self.assertTrue(value)
        return value

    def login(self, login="owner", client=None, password=None):
        client = client or self.client
        token = self.token(client.get("/admin/login"))
        response = client.post("/admin/login", data={
            "login": login,
            "password": password if password is not None else self.password,
            "csrf_token": token,
        })
        return response

    def authenticated(self, login="owner", client=None):
        client = client or self.client
        response = self.login(login, client)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/admin/cities")
        return self.token(client.get("/admin/cities"))

    def city_data(self, csrf, **changes):
        data = {"code": "newcity", "name": "New city", "csrf_token": csrf}
        data.update(changes)
        return data

    def staff_data(self, csrf, **changes):
        data = {
            "login": "newadmin", "password": self.password,
            "role": "admin", "csrf_token": csrf,
        }
        data.update(changes)
        return data

    def count(self, model):
        with self.sessions() as session:
            return session.scalar(select(func.count()).select_from(model))

    def new_client(self):
        client = TestClient(self.app, follow_redirects=False)
        client.__enter__()
        self.other_clients.append(client)
        return client

    def assert_denied(self, response):
        self.assertIn(response.status_code, (401, 403, 303, 307), response.text)
        if response.status_code in (303, 307):
            self.assertTrue(response.headers["location"].startswith("/admin/login"))

    def test_anonymous_cannot_read_admin_or_json(self):
        for path in ("/admin/cities", "/admin/history", "/admin/staff",
                     "/api/cities", "/api/history", "/api/staff"):
            with self.subTest(path=path):
                self.assert_denied(self.client.get(path))

    def test_login_requires_matching_csrf(self):
        self.client.get("/admin/login")
        response = self.client.post("/admin/login", data={
            "login": "owner", "password": self.password,
            "csrf_token": "incorrect-token",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_login_rejects_foreign_origin(self):
        token = self.token(self.client.get("/admin/login"))
        response = self.client.post("/admin/login", data={
            "login": "owner", "password": self.password, "csrf_token": token,
        }, headers={"Origin": "https://different.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_non_ascii_csrf_is_rejected_without_server_error(self):
        self.client.get("/admin/login")
        response = self.client.post("/admin/login", data={
            "login": "owner", "password": self.password, "csrf_token": "\u00e9",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_malformed_origin_is_rejected_without_server_error(self):
        token = self.authenticated()
        response = self.client.post("/admin/cities", data=self.city_data(token),
                                    headers={"Origin": "http://["})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.Cities), 1)

    def test_oversized_urlencoded_form_is_rejected_before_login(self):
        token = self.token(self.client.get("/admin/login"))
        body = ("csrf_token=" + token + "&login=owner&password=" + "x" * 40000).encode()
        response = self.client.post("/admin/login", content=body,
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_oversized_streamed_form_without_length_is_rejected(self):
        token = self.token(self.client.get("/admin/login"))
        chunks = iter([
            ("csrf_token=" + token + "&login=owner&password=").encode(),
            b"x" * 20000,
            b"y" * 20000,
        ])
        response = self.client.post("/admin/login", content=chunks,
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertNotIn("content-length", response.request.headers)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_incorrect_password_does_not_create_session(self):
        response = self.login(password="incorrect-password")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.count(self.StaffSessions), 0)
        self.assertNotIn("admin_session", self.client.cookies)

    def test_login_stores_only_hashed_opaque_token(self):
        response = self.login()
        self.assertEqual(response.status_code, 303)
        token = self.client.cookies.get("admin_session")
        self.assertTrue(token)
        with self.sessions() as session:
            row = session.scalar(select(self.StaffSessions))
            self.assertEqual(row.token_hash, hashlib.sha256(token.encode()).hexdigest())
            self.assertNotEqual(row.token_hash, token)
            self.assertEqual(row.user_id, self.owner_id)
        headers = response.headers.get_list("set-cookie")
        cookie = next(value for value in headers if value.startswith("admin_session="))
        self.assertIn("httponly", cookie.lower())
        self.assertIn("samesite=strict", cookie.lower())

    def test_admin_can_create_city(self):
        token = self.authenticated("operator")
        response = self.client.post("/admin/cities", data=self.city_data(token))
        self.assertEqual(response.status_code, 303, response.text)
        with self.sessions() as session:
            city = session.scalar(select(self.Cities).where(self.Cities.code == "newcity"))
            self.assertIsNotNone(city)
            self.assertEqual(city.name, "New city")
            self.assertEqual(city.threat, self.ThreatEnum.CALM)
            self.assertFalse(city.monitoring_enabled)

    def test_duplicate_city_is_conflict_without_duplicate_row(self):
        token = self.authenticated()
        response = self.client.post("/admin/cities", data=self.city_data(token, code="dnipro"))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count(self.Cities), 1)

    def test_city_validation_rejects_empty_or_long_fields(self):
        token = self.authenticated()
        for changes in ({"code": ""}, {"name": "   "}, {"name": "x" * 26}):
            with self.subTest(changes=changes):
                response = self.client.post("/admin/cities", data=self.city_data(token, **changes))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.count(self.Cities), 1)

    def test_city_post_requires_session_csrf(self):
        self.authenticated()
        response = self.client.post("/admin/cities", data={"code": "newcity", "name": "New city"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.Cities), 1)

    def test_city_form_cannot_set_threat_or_monitoring(self):
        token = self.authenticated()
        response = self.client.post("/admin/cities", data=self.city_data(
            token, threat="ballistics", monitoring_enabled="true",
        ))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.count(self.Cities), 1)

    def test_admin_can_update_city_name(self):
        token = self.authenticated("operator")
        response = self.client.post(f"/admin/cities/{self.city_id}/edit", data={
            "name": "Updated city", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 303, response.text)
        with self.sessions() as session:
            city = session.get(self.Cities, self.city_id)
            self.assertEqual(city.name, "Updated city")
            self.assertEqual(city.threat, self.ThreatEnum.CALM)

    def test_authenticated_mutation_rejects_foreign_origin(self):
        token = self.authenticated()
        response = self.client.post("/admin/cities", data=self.city_data(token),
                                    headers={"Origin": "https://different.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.Cities), 1)

    def test_city_code_cannot_be_changed_by_edit_form(self):
        token = self.authenticated()
        response = self.client.post(f"/admin/cities/{self.city_id}/edit", data={
            "code": "renamed", "name": "Renamed city", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 422, response.text)
        with self.sessions() as session:
            city = session.get(self.Cities, self.city_id)
            self.assertEqual(city.code, "dnipro")
            self.assertEqual(city.name, "Dnipro")

    def test_edit_form_cannot_enable_monitoring(self):
        token = self.authenticated()
        response = self.client.post(f"/admin/cities/{self.city_id}/edit", data={
            "name": "Renamed city", "monitoring_enabled": "true", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 422, response.text)
        with self.sessions() as session:
            city = session.get(self.Cities, self.city_id)
            self.assertEqual(city.name, "Dnipro")
            self.assertFalse(city.monitoring_enabled)

    def test_history_reads_nullable_threat_and_escapes_message(self):
        with self.sessions.begin() as session:
            session.add(self.ClassificationHistory(
                city_id=self.city_id, source_chat_id=123, source_message_id=456,
                telegram_message='<script>alert("x")</script>',
                first_answer="Нет", final_answer="Нет", threat=None,
                occurred_at=datetime.now(timezone.utc),
            ))
        self.authenticated("operator")
        response = self.client.get("/admin/history")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('<script>alert("x")</script>', response.text)
        self.assertIn("&lt;script&gt;", response.text)
        self.assertIn("Dnipro", response.text)
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["threat"])
        self.assertEqual(rows[0]["city_id"], self.city_id)

    def test_empty_city_filter_reads_history_without_validation_error(self):
        self.authenticated()
        for path in ("/admin/history?city_id=", "/api/history?city_id="):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)

    def test_regular_admin_cannot_manage_staff(self):
        token = self.authenticated("operator")
        for path in ("/admin/staff", "/api/staff"):
            self.assertEqual(self.client.get(path).status_code, 403)
        response = self.client.post("/admin/staff", data=self.staff_data(token, role="superadmin"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(self.StaffUsers), 2)

    def test_superadmin_can_create_hashed_staff_account(self):
        token = self.authenticated()
        response = self.client.post("/admin/staff", data=self.staff_data(token))
        self.assertEqual(response.status_code, 303, response.text)
        with self.sessions() as session:
            user = session.scalar(select(self.StaffUsers).where(self.StaffUsers.login == "newadmin"))
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, self.password)
            self.assertTrue(PasswordHash.recommended().verify(self.password, user.password_hash))
            self.assertEqual(user.role, self.StaffRole.ADMIN)

    def test_staff_login_uniqueness_is_case_insensitive(self):
        token = self.authenticated()
        response = self.client.post("/admin/staff", data=self.staff_data(token, login="OWNER"))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count(self.StaffUsers), 2)

    def test_staff_read_never_exposes_password_hash(self):
        self.authenticated()
        for path in ("/admin/staff", "/api/staff"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn(self.password_hash, response.text)
            self.assertNotIn(self.password, response.text)
            self.assertNotIn("password_hash", response.text)

    def test_last_superadmin_cannot_be_demoted_or_blocked(self):
        token = self.authenticated()
        for data in (
            {"role": "admin", "is_active": "on", "csrf_token": token},
            {"role": "superadmin", "csrf_token": token},
        ):
            with self.subTest(data=data):
                response = self.client.post(f"/admin/staff/{self.owner_id}/update", data=data)
                self.assertEqual(response.status_code, 409, response.text)
        with self.sessions() as session:
            owner = session.get(self.StaffUsers, self.owner_id)
            self.assertEqual(owner.role, self.StaffRole.SUPERADMIN)
            self.assertTrue(owner.is_active)

    def test_concurrent_superadmins_cannot_demote_each_other(self):
        from services import staff

        with self.sessions.begin() as session:
            session.get(self.StaffUsers, self.operator_id).role = self.StaffRole.SUPERADMIN
        owner_token = self.authenticated()
        operator = self.new_client()
        operator_token = self.authenticated("operator", operator)
        barrier = Barrier(2)
        update_staff = staff.update_staff

        def synchronized_update(*args, **kwargs):
            barrier.wait(timeout=5)
            return update_staff(*args, **kwargs)

        def demote(client, target_id, csrf):
            return client.post(f"/admin/staff/{target_id}/update", data={
                "role": "admin", "is_active": "on", "csrf_token": csrf,
            }).status_code

        with patch.object(staff, "update_staff", synchronized_update), ThreadPoolExecutor(max_workers=2) as executor:
            owner_request = executor.submit(demote, self.client, self.operator_id, owner_token)
            operator_request = executor.submit(demote, operator, self.owner_id, operator_token)
            statuses = [owner_request.result(timeout=20), operator_request.result(timeout=20)]

        self.assertEqual(statuses.count(303), 1, statuses)
        self.assertTrue(all(status in (303, 403, 409) for status in statuses), statuses)
        with self.sessions() as session:
            active_superadmins = session.scalar(select(func.count()).select_from(self.StaffUsers).where(
                self.StaffUsers.role == self.StaffRole.SUPERADMIN,
                self.StaffUsers.is_active.is_(True),
            ))
            self.assertEqual(active_superadmins, 1)

    def test_expired_session_is_rejected(self):
        self.authenticated()
        with self.sessions.begin() as session:
            row = session.scalar(select(self.StaffSessions))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assert_denied(self.client.get("/admin/cities"))

    def test_disabled_staff_cannot_login(self):
        with self.sessions.begin() as session:
            session.get(self.StaffUsers, self.operator_id).is_active = False
        response = self.login("operator")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_blocking_staff_invalidates_existing_access(self):
        operator = self.new_client()
        self.authenticated("operator", operator)
        token = self.authenticated()
        response = self.client.post(f"/admin/staff/{self.operator_id}/update", data={
            "role": "admin", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 303, response.text)
        self.assert_denied(operator.get("/admin/cities"))

    def test_demotion_changes_permissions_of_existing_session(self):
        with self.sessions.begin() as session:
            session.get(self.StaffUsers, self.operator_id).role = self.StaffRole.SUPERADMIN
        operator = self.new_client()
        self.authenticated("operator", operator)
        self.assertEqual(operator.get("/admin/staff").status_code, 200)
        token = self.authenticated()
        response = self.client.post(f"/admin/staff/{self.operator_id}/update", data={
            "role": "admin", "is_active": "on", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(operator.get("/admin/staff").status_code, 403)
        self.assertEqual(operator.get("/admin/cities").status_code, 200)

    def test_login_limiter_blocks_repeated_attempts(self):
        for _ in range(10):
            response = self.login(password="incorrect-password")
            self.assertEqual(response.status_code, 401, response.text)
        response = self.login(password="incorrect-password")
        self.assertEqual(response.status_code, 429, response.text)
        self.assertEqual(self.count(self.StaffSessions), 0)

    def test_logout_requires_csrf_and_revokes_server_session(self):
        token = self.authenticated()
        cookie = self.client.cookies.get("admin_session")
        response = self.client.post("/admin/logout", data={})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/admin/logout", data={"csrf_token": token})
        self.assertEqual(response.status_code, 303, response.text)
        self.assertNotIn("admin_session", self.client.cookies)
        replay = self.new_client()
        replay.cookies.set("admin_session", cookie)
        self.assert_denied(replay.get("/admin/cities"))


if __name__ == "__main__":
    unittest.main()
