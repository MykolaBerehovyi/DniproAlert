from alembic import op
from sqlalchemy import inspect

revision = '0001_alpha'
down_revision = None
branch_labels = None
depends_on = None

TABLES = {'cities': ['code', 'id', 'monitoring_enabled', 'name', 'threat'],
 'staff_users': ['created_at', 'id', 'is_active', 'login', 'password_hash', 'role'],
 'classification_history': ['city_id',
                            'created_at',
                            'final_answer',
                            'first_answer',
                            'id',
                            'occurred_at',
                            'source_chat_id',
                            'source_message_id',
                            'telegram_message',
                            'threat'],
 'clients': ['city_id', 'created_at', 'fcm_token', 'id', 'is_active'],
 'staff_sessions': ['created_at',
                    'csrf_token',
                    'expires_at',
                    'id',
                    'token_hash',
                    'user_id']}

DDL = (
    "CREATE TYPE threat AS ENUM ('calm', 'drones', 'ballistics', 'combined', 'redLevel')",
    "CREATE TYPE staff_role AS ENUM ('admin', 'superadmin')",
    """CREATE TABLE cities (
        id SERIAL NOT NULL,
        code VARCHAR(25) NOT NULL,
        name VARCHAR(25) NOT NULL,
        threat threat DEFAULT 'calm' NOT NULL,
        monitoring_enabled BOOLEAN DEFAULT false NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (code)
    )""",
    """CREATE TABLE staff_users (
        id SERIAL NOT NULL,
        login VARCHAR(50) NOT NULL,
        password_hash TEXT NOT NULL,
        role staff_role NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (login)
    )""",
    """CREATE TABLE clients (
        id SERIAL NOT NULL,
        fcm_token TEXT NOT NULL,
        city_id INTEGER NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (fcm_token),
        FOREIGN KEY(city_id) REFERENCES cities (id)
    )""",
    'CREATE INDEX ix_clients_city_active ON clients (city_id, is_active)',
    """CREATE TABLE classification_history (
        id SERIAL NOT NULL,
        city_id INTEGER NOT NULL,
        source_chat_id BIGINT NOT NULL,
        source_message_id BIGINT NOT NULL,
        telegram_message TEXT NOT NULL,
        first_answer TEXT NOT NULL,
        final_answer TEXT NOT NULL,
        threat threat,
        occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_history_source_city UNIQUE (city_id, source_chat_id, source_message_id),
        FOREIGN KEY(city_id) REFERENCES cities (id)
    )""",
    'CREATE INDEX ix_history_occurred ON classification_history (occurred_at)',
    'CREATE INDEX ix_history_city_occurred ON classification_history (city_id, occurred_at)',
    """CREATE TABLE staff_sessions (
        id SERIAL NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        user_id INTEGER NOT NULL,
        csrf_token VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (token_hash),
        FOREIGN KEY(user_id) REFERENCES staff_users (id) ON DELETE CASCADE
    )""",
    'CREATE INDEX ix_staff_sessions_user_id ON staff_sessions (user_id)',
    'CREATE INDEX ix_staff_sessions_expires_at ON staff_sessions (expires_at)',
)


def upgrade():
    if not op.get_context().as_sql:
        inspector = inspect(op.get_bind())
        existing = set(inspector.get_table_names()) & TABLES.keys()
        if existing:
            if existing != TABLES.keys():
                raise RuntimeError("Incomplete Alpha database schema")
            for table, columns in TABLES.items():
                actual = {column["name"] for column in inspector.get_columns(table)}
                if actual != set(columns):
                    raise RuntimeError(f"Unexpected Alpha columns in {table}")
            return
    for statement in DDL:
        op.execute(statement)


def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP TYPE staff_role")
    op.execute("DROP TYPE threat")
