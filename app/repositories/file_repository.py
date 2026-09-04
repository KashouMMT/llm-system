import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.utils.logger import logger

_FILE_COLUMNS = """
    id,
    conversation_id,
    message_id,
    user_id,
    document_type,
    filename,
    storage_key,
    content_type,
    size_bytes,
    created_at
"""


@dataclass(frozen=True)
class GeneratedFile:
    """
    One document produced by a tool call, and where its bytes live.

    conversation_id and user_id are reachable through message_id, and are
    stored anyway: the download authorization check becomes one indexed
    read with no joins, and "every file in this conversation" is a direct
    query. Safe to denormalize only because both are immutable — a file
    never moves conversation, and a conversation never changes owner.
    """

    id: UUID
    conversation_id: UUID
    message_id: int
    user_id: UUID
    document_type: str
    filename: str
    storage_key: str
    content_type: str
    size_bytes: int
    created_at: datetime


class FileRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(
        self,
        conversation_id: UUID,
        message_id: int,
        user_id: UUID,
        document_type: str,
        filename: str,
        storage_key: str,
        content_type: str,
        size_bytes: int,
    ) -> GeneratedFile:
        """
        Record a file whose bytes are already written.

        Called only after the write succeeded. The reverse order would
        allow a row pointing at bytes that do not exist, which is a
        download the user watches fail; this order can only leave an
        unreferenced blob, which is invisible and sweepable.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(GeneratedFile)) as cur,
        ):
            await cur.execute(
                f"""
                INSERT INTO generated_files (
                    id,
                    conversation_id,
                    message_id,
                    user_id,
                    document_type,
                    filename,
                    storage_key,
                    content_type,
                    size_bytes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_FILE_COLUMNS}
                """,
                (
                    uuid.uuid4(),
                    conversation_id,
                    message_id,
                    user_id,
                    document_type,
                    filename,
                    storage_key,
                    content_type,
                    size_bytes,
                ),
            )

            created = await cur.fetchone()

        logger.info(
            "Generated file recorded | file=%s type=%s conversation=%s bytes=%s",
            created.id,
            document_type,
            conversation_id,
            size_bytes,
        )

        return created

    async def get_by_id(self, file_id: UUID) -> GeneratedFile | None:
        """
        Fetch one file row.

        Ownership is deliberately not filtered here. The route compares
        user_id and returns 404, matching require_conversation — the same
        rule in one place rather than two.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(GeneratedFile)) as cur,
        ):
            await cur.execute(
                f"""
                SELECT {_FILE_COLUMNS}
                FROM generated_files
                WHERE id = %s
                """,
                (file_id,),
            )

            return await cur.fetchone()

    async def get_by_message_ids(
        self,
        message_ids: Sequence[int],
    ) -> list[GeneratedFile]:
        """
        Every file attached to any of these messages.

        One query for a whole transcript rather than one per message, since
        the caller is rendering a page of messages at once.
        """
        if not message_ids:
            return []

        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(GeneratedFile)) as cur,
        ):
            await cur.execute(
                f"""
                SELECT {_FILE_COLUMNS}
                FROM generated_files
                WHERE message_id = ANY(%s)
                ORDER BY created_at ASC
                """,
                (list(message_ids),),
            )

            return await cur.fetchall()