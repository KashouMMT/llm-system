from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.utils.logger import logger


@dataclass(frozen=True)
class Message:
    """
    A transcript message as the model context needs it.

    Named fields rather than a tuple: adding a column to a SELECT used to
    break every caller that unpacked the row positionally.
    """

    id: int
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class MessageDetail:
    """A transcript message as clients need it, including its status."""

    id: int
    role: str
    content: str
    created_at: datetime
    status: str


@dataclass(frozen=True)
class TurnLookup:
    """Both sides of a turn, resolved from a client idempotency key."""

    conversation_id: UUID
    user_message_id: int
    assistant_message_id: int | None


# Rows that must never reach the model: an in-flight assistant row is empty
# by definition, and an interrupted one can be.
HISTORY_FILTER = "status <> 'streaming' AND content <> ''"


class MessageRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_messages(
        self,
        conversation_id: UUID,
    ) -> Sequence[MessageDetail]:
        """
        Full transcript for display, including in-flight and failed rows.

        Callers rendering this must respect `status` — an unfinished answer
        must not be presented as a complete one.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(MessageDetail)) as cur,
        ):
            await cur.execute(
                """
                SELECT
                    id,
                    role,
                    content,
                    created_at,
                    status
                FROM messages
                WHERE conversation_id = %s
                ORDER BY id ASC
                """,
                (conversation_id,),
            )

            rows = await cur.fetchall()

            logger.debug(
                "Loaded %s messages | conversation=%s",
                len(rows),
                conversation_id,
            )

            return rows

    async def get_messages_after_id(
        self,
        conversation_id: UUID,
        message_id: int,
        before_message_id: int | None = None,
    ) -> Sequence[Message]:
        """
        Transcript slice for model context.

        before_message_id excludes the turn currently being generated. The
        current user message belongs to the graph's active turn state, so
        including it here would show the model the same question twice.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(Message)) as cur,
        ):
            await cur.execute(
                f"""
                SELECT
                    id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE conversation_id = %s
                  AND id > %s
                  AND (%s::BIGINT IS NULL OR id < %s)
                  AND {HISTORY_FILTER}
                ORDER BY id ASC
                """,
                (
                    conversation_id,
                    message_id,
                    before_message_id,
                    before_message_id,
                ),
            )

            rows = await cur.fetchall()

            logger.debug(
                "Loaded %s unsummarized messages | conversation=%s",
                len(rows),
                conversation_id,
            )

            return rows

    async def get_latest_message_id(
        self,
        conversation_id: UUID,
    ) -> int:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                f"""
                SELECT COALESCE(MAX(id), 0)
                FROM messages
                WHERE conversation_id = %s
                  AND {HISTORY_FILTER}
                """,
                (conversation_id,),
            )

            result = await cur.fetchone()

            return result[0]

    async def get_recent_messages(
        self,
        conversation_id: UUID,
        limit: int = 20,
    ) -> Sequence[Message]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(Message)) as cur,
        ):
            await cur.execute(
                f"""
                SELECT
                    id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE conversation_id = %s
                  AND {HISTORY_FILTER}
                ORDER BY id DESC
                LIMIT %s
                """,
                (conversation_id, limit),
            )

            rows = await cur.fetchall()

            rows.reverse()

            logger.debug(
                "Loaded %s recent messages | conversation=%s",
                len(rows),
                conversation_id,
            )

            return rows

    async def complete_message(
        self,
        message_id: int,
        content: str,
        status: str,
    ) -> None:
        """
        Write the buffered response and its terminal status in one update.

        One write per turn, not one per token: the buffer lives in memory
        while generating, and this is the single flush.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                UPDATE messages
                SET
                    content = %s,
                    status = %s
                WHERE id = %s
                """,
                (content, status, message_id),
            )

            if cur.rowcount != 1:
                raise ValueError(f"Message not found: {message_id}")

        logger.debug(
            "Message finalized | message=%s status=%s chars=%s",
            message_id,
            status,
            len(content),
        )

    async def get_turn_by_client_message_id(
        self,
        client_message_id: UUID,
    ) -> TurnLookup | None:
        """
        Resolve a client idempotency key back to the turn it created.

        Lets a retried send return the original ids instead of generating a
        second answer to the same question.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(TurnLookup)) as cur,
        ):
            await cur.execute(
                """
                SELECT
                    user_message.conversation_id AS conversation_id,
                    user_message.id              AS user_message_id,
                    assistant_message.id         AS assistant_message_id
                FROM messages AS user_message
                LEFT JOIN messages AS assistant_message
                    ON assistant_message.reply_to_message_id
                        = user_message.id
                WHERE user_message.client_message_id = %s
                """,
                (client_message_id,),
            )

            return await cur.fetchone()

    async def sweep_streaming(
        self,
        status: str = "interrupted",
    ) -> int:
        """
        Resolve rows abandoned mid-generation by a previous process.

        A crash leaves assistant rows at 'streaming' with nobody generating
        them. Run once at startup so no row is stuck in-flight forever.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                UPDATE messages
                SET status = %s
                WHERE status = 'streaming'
                """,
                (status,),
            )

            swept = cur.rowcount

        if swept:
            logger.warning(
                "Swept orphaned streaming messages | count=%s status=%s",
                swept,
                status,
            )

        return swept
