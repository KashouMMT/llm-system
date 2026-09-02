import psycopg

from app.config.settings import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from app.database.connection import get_connection
from app.database.migrations import run_migrations
from app.utils.logger import logger


def create_db_if_not_exist() -> None:
    conn = psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname="postgres",
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True,
    )

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM pg_database
                WHERE datname = %s
                """,
                (DB_NAME,),
            )

            exists = cur.fetchone()

            if exists:
                logger.info(f"Database already exists: {DB_NAME}")
                return

            cur.execute(f"CREATE DATABASE {DB_NAME}")

            logger.info(f"Database created: {DB_NAME}")

    finally:
        conn.close()


def create_tables() -> None:

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # ---------------------------------------------------------
            # Users
            # ---------------------------------------------------------
            # username is stored already-lowercased by the repository, so a
            # plain UNIQUE is enough for case-insensitive identity without
            # needing the citext extension.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    CONSTRAINT users_role_check
                        CHECK (role IN ('user', 'admin', 'root'))
                )
            """
            )

            # At most one root user, enforced by the database.
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_users_single_root
                ON users (role)
                WHERE role = 'root'
            """
            )

            # ---------------------------------------------------------
            # Sessions
            # ---------------------------------------------------------
            # token_hash is sha256(opaque token). The raw token lives only
            # in the client's cookie, so a database dump yields no usable
            # sessions. The UNIQUE constraint is also the per-request
            # lookup index.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id BIGSERIAL PRIMARY KEY,
                    token_hash BYTEA UNIQUE NOT NULL,
                    user_id UUID NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,

                    CONSTRAINT fk_sessions_user
                        FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                )
            """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                ON sessions(user_id)
            """
            )

            # ---------------------------------------------------------
            # Conversations
            # ---------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    title TEXT NOT NULL DEFAULT 'New Conversation',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),

                    CONSTRAINT conversations_status_check
                        CHECK (status IN ('active', 'held', 'closed')),
                    CONSTRAINT fk_conversations_user
                        FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                )
            """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_user_id
                ON conversations(user_id)
            """
            )

            # ---------------------------------------------------------
            # Messages
            # ---------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    conversation_id UUID NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),

                    CONSTRAINT fk_messages_conversation
                        FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
            )
            """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages(conversation_id)
            """
            )

            # ---------------------------------------------------------
            # Current conversation summary
            # ---------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_summary_state (
                    conversation_id UUID PRIMARY KEY,
                    summary TEXT NOT NULL,
                    last_summarized_message_id BIGINT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW(),

                    CONSTRAINT fk_summary_state_conversation
                        FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                )
            """
            )

            # ---------------------------------------------------------
            # Historical summary chunks
            # ---------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id BIGSERIAL PRIMARY KEY,
                    conversation_id UUID NOT NULL,
                    start_message_id BIGINT NOT NULL,
                    end_message_id BIGINT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),

                    CONSTRAINT fk_summary_conversation
                        FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                )
            """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_summary_conversation_id
                ON conversation_summaries(conversation_id)
            """
            )

            # ---------------------------------------------------------
            # Runtime-adjustable settings
            # ---------------------------------------------------------
            # Sparse on purpose: one row per key that has actually been
            # overridden. An absent key falls through to the environment,
            # so editing .env keeps working, and resetting a setting is a
            # DELETE rather than writing the default back.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """
            )

            conn.commit()

            logger.info("Database tables initialized")

    finally:
        conn.close()


def initialize_database() -> None:
    create_db_if_not_exist()
    create_tables()
    run_migrations()

    logger.info("Database initialization complete")
