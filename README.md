# Dnipro Alert Backend

Backend service for Dnipro Alert. It reads messages from a configured Telegram channel, sends them through two AI classification steps, stores the result in PostgreSQL, and sends confirmed events through Firebase Cloud Messaging (FCM).

The Telegram worker and AI prompts currently support Dnipro. Adding another city to the database does not create a Telegram handler for that city.

## Message flow

1. The Telegram worker reads new messages through Telethon.
2. The backend stores each message in the classification history.
3. A classifier produces a preliminary answer and a separate verifier checks it. Only the verifier's final answer determines the threat.
4. The backend updates the city's current status.
5. For a confirmed threat, the backend sends an FCM data message to active clients in that city.
6. The mobile app receives the push and can request the current status from the API.

The worker also runs retention to remove old classification records, deactivated clients, and expired admin sessions.

## Technology stack

| Technology | Purpose |
|---|---|
| Python | Backend language |
| FastAPI | HTTP API and admin routes |
| Uvicorn | ASGI server for FastAPI |
| Pydantic v2 and pydantic-settings | Request validation and loading settings from .env |
| SQLAlchemy 2 | ORM and PostgreSQL transactions; API database sessions are synchronous |
| PostgreSQL 17 | Persistent data storage |
| Alembic | Versioned database schema migrations |
| Docker Compose | Local PostgreSQL startup |
| Telethon | Reading Telegram messages through an authorized session |
| OpenAI Python SDK | Two-step message classification |
| Firebase Admin SDK | App Check verification and FCM delivery |
| Jinja2 | Server-rendered admin pages |
| pwdlib with Argon2 | Staff password hashing |
| unittest and FastAPI TestClient | API and integration tests |

## File map

### Project root

- **compose.yaml** — local PostgreSQL container configuration.
- **requirements.txt** — Python dependencies with pinned versions.
- **start_backend.bat** — starts PostgreSQL, the API, and the Telegram worker on Windows.
- **start_ngrok.bat** — machine-specific local tunnel helper; intentionally ignored by Git because it may contain a private tunnel URL. Use the generic ngrok command below for a public checkout.
- **alembic.ini** — base Alembic configuration.
- **.gitignore** — excludes local secrets, Telegram sessions, and Python environment files.

### app/

- **main.py** — creates the FastAPI app, connects routes and templates, configures middleware, and exposes the database health check.
- **config.py** — defines Pydantic Settings loaded from .env.
- **database.py** — creates the SQLAlchemy engine, database sessions, and model base class.
- **models.py** — ORM models for cities, clients, classification history, staff users, and staff sessions.
- **schemas.py** — Pydantic validation and response schemas.
- **enums.py** — threat types and staff roles.
- **prompts.py** — prompts for the classifier and verifier models.
- **security.py** — authentication dependencies, role checks, CSRF validation, and request-size limits.
- **worker.py** — background Telegram listener, AI processing loop, and retention scheduler.
- **schema_migrations.py** — runs Alembic upgrades under a database lock.
- **authorize_telegram.py** — interactive Telegram authorization; creates a local session file.
- **create_superadmin.py** — creates the first superadmin account.
- **__init__.py** — marks the directory as a Python package.

### api/

- **admin.py** — admin pages and endpoints for cities, classification history, staff, and monitoring controls.
- **clients.py** — mobile client registration with Firebase App Check validation.
- **status.py** — returns the current city alert status to the mobile app.
- **__init__.py** — marks the directory as a Python package.

### services/

- **alerts.py** — ingests Telegram messages, tracks classification history, updates the city state, and sends FCM messages.
- **classifier.py** — calls the classifier and verifier and maps the final answer to a threat type.
- **clients.py** — registers and updates FCM tokens.
- **retention.py** — batch-deletes old records and expired sessions.
- **staff.py** — password hashing, admin sessions, login, and staff-role rules.

### integrations/

- **telegram.py** — connects Telethon to the configured channel and reads messages.
- **ai.py** — creates the OpenAI client.
- **firebase.py** — initializes Firebase Admin, verifies App Check tokens, and sends FCM messages.
- **__init__.py** — marks the directory as a Python package.

### repository/

- **clients.py** — database queries for cities and mobile clients.
- **admin.py** — database queries for admin pages, history, and staff.
- **__init__.py** — marks the directory as a Python package.

### app/templates/ and app/static/

- **base.html** — shared admin page layout.
- **login.html** — sign-in form.
- **cities.html** — city list.
- **city_edit.html** — city editing and monitoring toggle.
- **history.html** — classification history page.
- **staff.html** — staff management page.
- **error.html** — error page.
- **macros.html** — reusable Jinja fragments.
- **admin.css** — admin panel styles.
- **alert.svg** — admin panel icon.

### alembic/

- **env.py** — connects Alembic to SQLAlchemy metadata and the database engine.
- **script.py.mako** — template for new migrations.
- **versions/0001_alpha.py** — initial database schema.
- **versions/0002_mobile_mobile_alerts.py** — schema changes for mobile clients and message processing.
- **versions/0003_remove_delivery_jobs.py** — removes the unused delivery-jobs table.

### tests/ and presentation/

- **tests/test_mobile.py** — integration tests for mobile APIs, message processing, and retention.
- **tests/test_admin.py** — tests for authentication, roles, and the admin panel.
- **presentation/assets/database_erd.png** — database ER diagram.
- **presentation/assets/admin-cities.png** — city list screen.
- **presentation/assets/flutter/app-home.png** — mobile home screen mockup.
- **presentation/assets/flutter/app-settings.png** — mobile settings screen mockup.
- **presentation/assets/flutter/app-alarm.png** — mobile alarm screen mockup.

## Run on Windows

### 1. Prerequisites

- Python 3.12 or newer.
- Docker Desktop with Docker Compose running.
- Git.
- Telegram, OpenAI, and Firebase credentials for full alert processing.

### 2. Install Python dependencies

Run from the project root:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

Replace 3.12 with another installed, compatible Python version if needed.

### 3. Create a local .env file

Create .env in the project root. Do not add it to Git. Replace every example value:

~~~env
POSTGRES_PASSWORD=local_dev_password
DATABASE_URL=postgresql+psycopg://dnipro_alert:local_dev_password@127.0.0.1:5434/dnipro_alert

ALLOWED_HOSTS=["localhost","127.0.0.1","testserver"]
COOKIE_SECURE=false
SESSION_HOURS=8

TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=replace_with_telegram_api_hash
TELEGRAM_SOURCE=@your_test_channel
TELEGRAM_SESSION_PATH=telegram.session

OPENAI_API_KEY=replace_with_openai_api_key
OPENAI_CLASSIFIER_MODEL=gpt-5.4-mini
OPENAI_VERIFIER_MODEL=gpt-5.6-luna

FIREBASE_CREDENTIALS_PATH=credentials/firebase-service-account.json
APP_CHECK_ALLOWED_APP_IDS=your_firebase_android_app_id

ALERT_TTL_SECONDS=3600
RETENTION_INTERVAL_HOURS=12
~~~

POSTGRES_PASSWORD must match the password in DATABASE_URL. Put the Firebase service-account JSON in the local credentials directory. Never commit .env, Telegram session files, or Firebase service-account keys.

### 4. Start PostgreSQL

~~~powershell
docker compose up -d db
~~~

The startup script also runs this command, but PostgreSQL must be running before you create the initial admin account.

### 5. Authorize Telegram

Run once. Telegram will ask for a phone number, a login code, and, if enabled, the account's cloud password:

~~~powershell
.\.venv\Scripts\python.exe -m app.authorize_telegram
~~~

The command creates telegram.session locally. Do not add this session file to Git.

### 6. Create the first superadmin

~~~powershell
.\.venv\Scripts\python.exe -m app.create_superadmin --login admin
~~~

Enter a password from 12 to 128 characters. The command refuses to create another first superadmin if an active superadmin already exists.

### 7. Start the backend

~~~powershell
.\start_backend.bat
~~~

The script starts PostgreSQL and opens separate windows for the API and worker. Alembic migrations are applied during API or worker startup. If the Telegram session does not exist, complete step 5 first.

- Admin panel: http://127.0.0.1:8001/admin/login
- API docs: http://127.0.0.1:8001/docs
- API and database health check: http://127.0.0.1:8001/healthz

Sign in as a superadmin and enable monitoring for Dnipro. The worker processes new messages after monitoring is enabled; do not use older posts as test input.

### 8. Connect the Flutter app

The Flutter client is maintained separately from this backend. An Android emulator may not be able to reach the computer's localhost. For a temporary tunnel, run:

~~~powershell
ngrok http 8001
~~~

Pass the tunnel's HTTPS address to Flutter using the compile-time BACKEND_BASE_URL parameter. Add the tunnel hostname, without scheme or path, to ALLOWED_HOSTS. A Flutter debug build also needs an allowed Firebase App Check debug token. Do not publish tunnel URLs or debug tokens.

## Tests

Backend tests use unittest and require a separate PostgreSQL test database. Create it once:

~~~powershell
docker compose exec db createdb -U dnipro_alert dnipro_alert_test
~~~

Set TEST_DATABASE_URL to this test database. The tests create and remove isolated schemas inside it:

~~~powershell
$env:TEST_DATABASE_URL="postgresql+psycopg://user:password@127.0.0.1:5434/dnipro_alert_test"
.\.venv\Scripts\python.exe -m unittest discover -s tests
~~~

Never point TEST_DATABASE_URL at a development, demo, or production database.

## Mobile app

The Flutter client uses Dart/Flutter, Riverpod, Firebase Messaging, Firebase App Check, Dio, local notifications, and SQLite through sqflite. User settings remain on the device; the server receives the FCM token and city code. See the client repository's README for its file map and startup instructions.

