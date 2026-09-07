from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncCursor
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


class ConversationRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def _insert_conversation(
        self,
        cur: AsyncCursor[Any],
        user_id: UUID,
        title: str,
        first_message: str | None,
    ) -> UUID:
        """
        Insert a conversation and its optional greeting on a caller's cursor.

        Takes the cursor rather than opening its own connection so the
        caller owns the transaction boundary: get_or_create_active_draft
        needs this insert to run inside the same transaction that holds its
        advisory lock, and a nested connection would commit outside it.

        When `first_message` is given it is inserted as a complete
        `assistant` row in that same transaction, so a client never observes
        the conversation without its greeting. The row has no
        `reply_to_message_id` — it answers no user message — which the
        schema allows.
        """
        conversation_id = uuid4()

        await cur.execute(
            """
            INSERT INTO conversations (id, user_id, title)
            VALUES (%s, %s, %s)
            """,
            (conversation_id, user_id, title),
        )

        if first_message:
            await cur.execute(
                """
                INSERT INTO messages (conversation_id, role, content, status)
                VALUES (%s, %s, %s, %s)
                """,
                (conversation_id, "assistant", first_message, "complete"),
            )

        logger.info(
            "Conversation created | id=%s user=%s seeded_greeting=%s",
            conversation_id,
            user_id,
            first_message is not None,
        )

        return conversation_id

    async def create_conversation(
        self,
        user_id: UUID,
        title: str = "New Conversation",
        first_message: str | None = None,
    ) -> UUID:
        """Create a conversation unconditionally, in its own transaction."""
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            return await self._insert_conversation(
                cur,
                user_id=user_id,
                title=title,
                first_message=first_message,
            )

    async def get_or_create_active_draft(
        self,
        user_id: UUID,
        title: str = "New Conversation",
        first_message: str | None = None,
    ) -> UUID:
        """
        Return the user's newest unused conversation, creating one if there
        is none.

        "Unused" means active and carrying no `user` message. A conversation
        holding only the seeded assistant greeting still qualifies, which is
        what makes a freshly opened "New chat" reusable. Without this,
        clicking "New chat" repeatedly leaves behind a trail of empty
        conversations nobody can tell apart.

        Only `active` conversations are reused: resurrecting a closed one
        because it happens to be empty would quietly reopen something the
        user finished with.

        The lookup and the insert share one transaction guarded by an
        advisory lock keyed on the user. Two tabs clicking "New chat" at the
        same instant would otherwise both find nothing and both insert; the
        lock makes the second wait and then find the first one's row. It is
        keyed per user so unrelated users never queue behind each other, and
        `_xact_` releases it when the transaction ends, including on error.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            # hashtext is undocumented but has been stable in PostgreSQL for
            # many major versions; it is the ordinary way to key an advisory
            # lock on something that is not already a bigint. A collision
            # between two users only costs a brief wait.
            await cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (str(user_id),),
            )

            await cur.execute(
                """
                SELECT c.id
                FROM conversations c
                WHERE c.user_id = %s
                  AND c.status = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM messages m
                      WHERE m.conversation_id = c.id
                        AND m.role = 'user'
                  )
                ORDER BY c.created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )

            row = await cur.fetchone()

            if row is not None:
                logger.info(
                    "Conversation reused | id=%s user=%s",
                    row[0],
                    user_id,
                )

                return row[0]

            return await self._insert_conversation(
                cur,
                user_id=user_id,
                title=title,
                first_message=first_message,
            )

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