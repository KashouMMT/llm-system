import psycopg

from app.config.settings import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from app.database.connection import get_connection
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
            # Conversations
            # ---------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New Conversation',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
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

            conn.commit()

            logger.info("Database tables initialized")

    finally:
        conn.close()


def initialize_database() -> None:
    create_db_if_not_exist()
    create_tables()

    logger.info("Database initialization complete")
