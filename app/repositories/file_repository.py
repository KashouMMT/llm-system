import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.utils.logger import logger

_FILE_COLUMNS = """
    id,
    conversation_id,
    message_id,
    user_id,
    origin,
    document_type,
    filename,
    storage_key,
    content_type,
    size_bytes,
    created_at
"""


@dataclass(frozen=True)
class FileRecord:
    """
    One file — agent-generated or user-uploaded — and where its bytes live.

    conversation_id and user_id are reachable through message_id, and are
    stored anyway: the download authorization check becomes one indexed
    read with no joins, and "every file in this conversation" is a direct
    query. Safe to denormalize only because both are immutable — a file
    never moves conversation, and a conversation never changes owner.

    message_id is None for an uploaded file that has not yet been attached
    to a message. document_type is None for an uploaded file: only a
    generated document has one. The two track each other via the
    files_origin_document_type_check constraint, not application code.
    """

    id: UUID
    conversation_id: UUID
    message_id: int | None
    user_id: UUID
    origin: str
    document_type: str | None
    filename: str
    storage_key: str
    content_type: str
    size_bytes: int
    created_at: datetime


def serialize_attachment(file: FileRecord) -> dict[str, Any]:
    """
    The wire shape for one attachment.

    Shared by the message-list endpoint and the message.created event so
    the two can never drift apart. storage_key is deliberately excluded —
    a client addresses a file by id through GET /files/{id}, and where the
    bytes actually live is not its business.

    created_at is pre-formatted to ISO text rather than left as a
    datetime: the message-list endpoint's JSONResponse would encode either
    one, but the message.created event reaches format_sse's plain
    json.dumps, which does not know how to serialize a datetime — the same
    reason every other timestamp built into an event payload elsewhere in
    this codebase is already .isoformat()'d before it gets there.
    """
    return {
        "id": str(file.id),
        "document_type": file.document_type,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": file.size_bytes,
        "created_at": file.created_at.isoformat(),
    }


class FileRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(
        self,
        conversation_id: UUID,
        user_id: UUID,
        origin: str,
        filename: str,
        storage_key: str,
        content_type: str,
        size_bytes: int,
        message_id: int | None = None,
        document_type: str | None = None,
    ) -> FileRecord:
        """
        Record a file whose bytes are already written.

        Called only after the write succeeded. The reverse order would
        allow a row pointing at bytes that do not exist, which is a
        download the user watches fail; this order can only leave an
        unreferenced blob, which is invisible and sweepable.

        message_id and document_type default to None for an uploaded file:
        an upload is recorded before it is attached to any message, and
        never has a document_type. The database enforces the pairing
        (files_origin_document_type_check) rather than this method, so a
        caller cannot drift from it silently.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(FileRecord)) as cur,
        ):
            await cur.execute(
                f"""
                INSERT INTO files (
                    id,
                    conversation_id,
                    message_id,
                    user_id,
                    origin,
                    document_type,
                    filename,
                    storage_key,
                    content_type,
                    size_bytes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_FILE_COLUMNS}
                """,
                (
                    uuid.uuid4(),
                    conversation_id,
                    message_id,
                    user_id,
                    origin,
                    document_type,
                    filename,
                    storage_key,
                    content_type,
                    size_bytes,
                ),
            )

            created = await cur.fetchone()

        logger.info(
            "File recorded | file=%s origin=%s type=%s conversation=%s bytes=%s",
            created.id,
            origin,
            document_type,
            conversation_id,
            size_bytes,
        )

        return created

    async def get_by_id(self, file_id: UUID) -> FileRecord | None:
        """
        Fetch one file row.

        Ownership is deliberately not filtered here. The route compares
        user_id and returns 404, matching require_conversation — the same
        rule in one place rather than two.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(FileRecord)) as cur,
        ):
            await cur.execute(
                f"""
                SELECT {_FILE_COLUMNS}
                FROM files
                WHERE id = %s
                """,
                (file_id,),
            )

            return await cur.fetchone()

    async def get_by_message_ids(
        self,
        message_ids: Sequence[int],
    ) -> list[FileRecord]:
        """
        Every file attached to any of these messages.

        One query for a whole transcript rather than one per message, since
        the caller is rendering a page of messages at once.
        """
        if not message_ids:
            return []

        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(FileRecord)) as cur,
        ):
            await cur.execute(
                f"""
                SELECT {_FILE_COLUMNS}
                FROM files
                WHERE message_id = ANY(%s)
                ORDER BY created_at ASC
                """,
                (list(message_ids),),
            )

            return await cur.fetchall()

    async def sweep_orphaned_uploads(
        self,
        *,
        older_than_hours: int = 24,
    ) -> list[str]:
        """
        Delete uploaded rows that were never attached to a message and are
        old enough that the sender is not still mid-send.

        Run once at startup, alongside MessageRepository.sweep_streaming.
        The row is deleted first and the bytes after: the reverse order can
        leave a row pointing at bytes that no longer exist (this
        application's one recognized inconsistency, already handled as a
        logged 404 in GET /files/{id}), while this order can only leave an
        unreferenced blob — invisible, harmless, and swept again next time
        if it is somehow missed.

        Returns the storage keys of the deleted rows, so the caller can
        remove their bytes.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                DELETE FROM files
                WHERE origin = 'uploaded'
                  AND message_id IS NULL
                  AND created_at < NOW() - (%s || ' hours')::INTERVAL
                RETURNING storage_key
                """,
                (older_than_hours,),
            )

            rows = await cur.fetchall()

        return [row[0] for row in rows]