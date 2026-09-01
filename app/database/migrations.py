from collections.abc import Sequence

from app.database.connection import get_connection
from app.utils.logger import logger

Migration = tuple[int, str, Sequence[str]]

MESSAGE_STATUSES = (
    "streaming",
    "complete",
    "interrupted",
    "cancelled",
    "failed",
)

MIGRATIONS: list[Migration] = [
    (
        1,
        "message status, idempotency key, turn linkage",
        (
            """
            ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'complete'
            """,
            """
            ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS client_message_id UUID
            """,
            """
            ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS reply_to_message_id BIGINT
            """,
            # Partial index: only client-originated messages carry a key, and
            # the database — not application logic — has to be what rejects a
            # duplicate, because retries race.
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_client_message_id
            ON messages (client_message_id)
            WHERE client_message_id IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_messages_reply_to_message_id
            ON messages (reply_to_message_id)
            WHERE reply_to_message_id IS NOT NULL
            """,
            f"""
            ALTER TABLE messages
            ADD CONSTRAINT messages_status_check
            CHECK (status IN ({", ".join(f"'{s}'" for s in MESSAGE_STATUSES)}))
            """,
        ),
    ),
    (
        2,
        "naive timestamps to timestamptz",
        (
            """
            ALTER TABLE conversations
                ALTER COLUMN created_at TYPE TIMESTAMPTZ
                    USING created_at AT TIME ZONE 'UTC',
                ALTER COLUMN updated_at TYPE TIMESTAMPTZ
                    USING updated_at AT TIME ZONE 'UTC'
            """,
            """
            ALTER TABLE messages
                ALTER COLUMN created_at TYPE TIMESTAMPTZ
                    USING created_at AT TIME ZONE 'UTC'
            """,
            """
            ALTER TABLE conversation_summary_state
                ALTER COLUMN updated_at TYPE TIMESTAMPTZ
                    USING updated_at AT TIME ZONE 'UTC'
            """,
            """
            ALTER TABLE conversation_summaries
                ALTER COLUMN created_at TYPE TIMESTAMPTZ
                    USING created_at AT TIME ZONE 'UTC'
            """,
        ),
    ),
]


def _ensure_version_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

    conn.commit()


def _applied_versions(conn) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")

        return {row[0] for row in cur.fetchall()}


def run_migrations() -> None:
    """
    Apply every migration that has not run yet, oldest first.

    Each migration commits on its own, so a failure leaves the earlier ones
    applied and recorded. CREATE TABLE IF NOT EXISTS cannot express schema
    changes to a table that already exists, which is why this runner exists
    alongside create_tables().
    """
    conn = get_connection()

    try:
        _ensure_version_table(conn)

        applied = _applied_versions(conn)

        for version, description, statements in MIGRATIONS:
            if version in applied:
                continue

            try:
                with conn.cursor() as cur:
                    for statement in statements:
                        cur.execute(statement)

                    cur.execute(
                        """
                        INSERT INTO schema_migrations (version, description)
                        VALUES (%s, %s)
                        """,
                        (version, description),
                    )

                conn.commit()

                logger.info(
                    "Migration applied | version=%s description=%s",
                    version,
                    description,
                )

            except Exception:
                conn.rollback()

                logger.exception(
                    "Migration failed | version=%s description=%s",
                    version,
                    description,
                )

                raise

    finally:
        conn.close()