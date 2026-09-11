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
    A transcript message.

    Named fields rather than a tuple: adding a column to a SELECT used to
    break every caller that unpacked the row positionally.

    `status` lets a display caller tell an unfinished answer from a complete
    one; context and summarization callers select through HISTORY_FILTER and
    can ignore it.
    """

    id: int
    role: str
    content: str
    created_at: datetime
    status: str


@dataclass(frozen=True)
class Turn:
    """The two rows created when a turn is opened, before generation runs."""

    user_message_id: int
    user_created_at: datetime
    assistant_message_id: int
    assistant_created_at: datetime


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

    async def create_turn(
        self,
        conversation_id: UUID,
        user_content: str,
        client_message_id: UUID,
        user_id: UUID,
        max_attachment_batch_bytes: int,
        attachment_ids: Sequence[UUID] = (),
    ) -> Turn:
        """
        Open one conversation turn atomically, before generation starts.

        The user message is persisted immediately and unconditionally: it was
        typed by a person, and losing it because a connection dropped is the
        worst available outcome. The assistant row is created empty and
        'streaming' so every client can see that an answer is on its way, and
        so a crash leaves a visible row to sweep rather than silence.

        attachment_ids, when given, are uploaded files to attach to the new
        user message. The UPDATE below is both the ownership check and the
        attach: it only touches a row that is an unattached upload owned by
        this user in this conversation, so a stray or already-attached id
        cannot be smuggled in. Doing it inside this same block — rather than
        as a separate call after create_turn returns — is what makes a failed
        send leave the uploads unattached and reusable instead of half
        committed, and what makes a client_message_id retry a no-op: the
        UniqueViolation on the insert below fires before this UPDATE ever
        runs, so a retry can only reach this point once.

        max_attachment_batch_bytes bounds the combined size_bytes of what
        gets attached, checked from the same UPDATE's own RETURNING rather
        than a second query. The frontend already refuses to queue a batch
        this large, but that is a UX convenience — a direct API call is
        stopped here.

        The parent conversation's updated_at is bumped in the same
        transaction — every statement shares one connection block, which the
        pool commits on a clean exit and rolls back if it raises.

        Raises psycopg.errors.UniqueViolation if client_message_id was already
        used — that is the idempotency guard, enforced by the database because
        retries race. Raises ValueError if any attachment_ids do not resolve
        to an unattached upload owned by this user in this conversation, or if
        their combined size exceeds max_attachment_batch_bytes.
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

            # Deduplicated so a client sending the same id twice cannot make
            # this reject a perfectly valid attachment.
            unique_attachment_ids = list(dict.fromkeys(attachment_ids))

            if unique_attachment_ids:
                await cur.execute(
                    """
                    UPDATE files
                    SET message_id = %s
                    WHERE id = ANY(%s)
                      AND conversation_id = %s
                      AND user_id = %s
                      AND origin = 'uploaded'
                      AND message_id IS NULL
                    RETURNING size_bytes
                    """,
                    (
                        user_message_id,
                        unique_attachment_ids,
                        conversation_id,
                        user_id,
                    ),
                )

                attached_sizes = [row[0] for row in await cur.fetchall()]

                if len(attached_sizes) != len(unique_attachment_ids):
                    raise ValueError(
                        "One or more attachment_ids are invalid, already "
                        "attached, or do not belong to this conversation."
                    )

                if sum(attached_sizes) > max_attachment_batch_bytes:
                    raise ValueError(
                        "Attachments exceed the "
                        f"{max_attachment_batch_bytes}-byte limit for one "
                        "message."
                    )

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

    async def get_messages(
        self,
        conversation_id: UUID,
    ) -> Sequence[Message]:
        """
        Full transcript for display, including in-flight and failed rows.

        Callers rendering this must respect `status` — an unfinished answer
        must not be presented as a complete one.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(Message)) as cur,
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
                    created_at,
                    status
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
                    created_at,
                    status
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