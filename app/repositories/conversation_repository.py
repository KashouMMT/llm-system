from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.utils.logger import logger


@dataclass(frozen=True)
class Conversation:
    id: UUID
    user_id: UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Turn:
    """The two rows created when a turn is opened, before generation runs."""

    user_message_id: int
    user_created_at: datetime
    assistant_message_id: int
    assistant_created_at: datetime


class ConversationRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create_conversation(
        self,
        user_id: UUID,
        title: str = "New Conversation",
    ) -> UUID:
        conversation_id = uuid4()

        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                INSERT INTO conversations (id, user_id, title)
                VALUES (%s, %s, %s)
                """,
                (conversation_id, user_id, title),
            )

        logger.info(
            "Conversation created | id=%s user=%s",
            conversation_id,
            user_id,
        )

        return conversation_id

    async def get_conversation(
        self,
        conversation_id: UUID,
    ) -> Conversation | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(Conversation)) as cur,
        ):
            await cur.execute(
                """
                SELECT
                    id,
                    user_id,
                    title,
                    status,
                    created_at,
                    updated_at
                FROM conversations
                WHERE id = %s
                """,
                (conversation_id,),
            )

            return await cur.fetchone()

    async def get_conversations(
        self,
        user_id: UUID,
    ) -> Sequence[Conversation]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(Conversation)) as cur,
        ):
            await cur.execute(
                """
                SELECT
                    id,
                    user_id,
                    title,
                    status,
                    created_at,
                    updated_at
                FROM conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )

            rows = await cur.fetchall()

            logger.debug("Loaded %s conversations | user=%s", len(rows), user_id)

            return rows

    async def get_status(self, conversation_id: UUID) -> str | None:
        """Current lifecycle status, or None if the conversation is gone."""
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT status FROM conversations WHERE id = %s",
                (conversation_id,),
            )

            row = await cur.fetchone()

            return row[0] if row else None

    async def exists(
        self,
        conversation_id: UUID,
    ) -> bool:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM conversations
                    WHERE id = %s
                )
                """,
                (conversation_id,),
            )

            result = await cur.fetchone()

            return bool(result[0])

    async def create_turn(
        self,
        conversation_id: UUID,
        user_content: str,
        client_message_id: UUID,
    ) -> Turn:
        """
        Open one conversation turn atomically, before generation starts.

        The user message is persisted immediately and unconditionally: it was
        typed by a person, and losing it because a connection dropped is the
        worst available outcome. The assistant row is created empty and
        'streaming' so every client can see that an answer is on its way, and
        so a crash leaves a visible row to sweep rather than silence.

        All three statements share one transaction — the pool commits when the
        connection block exits cleanly and rolls back if it raises.

        Raises psycopg.errors.UniqueViolation if client_message_id was already
        used — that is the idempotency guard, enforced by the database because
        retries race.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                INSERT INTO messages (
                    conversation_id,
                    role,
                    content,
                    status,
                    client_message_id
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    conversation_id,
                    "user",
                    user_content,
                    "complete",
                    client_message_id,
                ),
            )

            user_message_id, user_created_at = await cur.fetchone()

            await cur.execute(
                """
                INSERT INTO messages (
                    conversation_id,
                    role,
                    content,
                    status,
                    reply_to_message_id
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    conversation_id,
                    "assistant",
                    "",
                    "streaming",
                    user_message_id,
                ),
            )

            assistant_message_id, assistant_created_at = await cur.fetchone()

            await cur.execute(
                """
                UPDATE conversations
                SET updated_at = NOW()
                WHERE id = %s
                """,
                (conversation_id,),
            )

            if cur.rowcount != 1:
                raise ValueError(f"Conversation not found: {conversation_id}")

        logger.debug(
            "Turn opened | conversation=%s user_message=%s assistant_message=%s",
            conversation_id,
            user_message_id,
            assistant_message_id,
        )

        return Turn(
            user_message_id=user_message_id,
            user_created_at=user_created_at,
            assistant_message_id=assistant_message_id,
            assistant_created_at=assistant_created_at,
        )

    async def update_title(
        self,
        conversation_id: UUID,
        title: str,
    ) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                UPDATE conversations
                SET
                    title = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    title,
                    conversation_id,
                ),
            )

        logger.debug(
            "Conversation title updated | id=%s",
            conversation_id,
        )

    async def touch(
        self,
        conversation_id: UUID,
    ) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                UPDATE conversations
                SET updated_at = NOW()
                WHERE id = %s
                """,
                (conversation_id,),
            )

    async def delete_conversation(
        self,
        conversation_id: UUID,
    ) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                DELETE FROM conversations
                WHERE id = %s
                """,
                (conversation_id,),
            )

        logger.info(
            "Conversation deleted | id=%s",
            conversation_id,
        )
