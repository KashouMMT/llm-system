from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.database.connection import get_connection
from app.utils.logger import logger

MessageRow = tuple[
    int,
    str,
    str,
    datetime,
]


class MessageRepository:
    def save_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
    ) -> int:

        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages (
                        conversation_id,
                        role,
                        content
                    )
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        conversation_id,
                        role,
                        content,
                    ),
                )

                message_id = cur.fetchone()[0]

                conn.commit()

                logger.debug(
                    f"Message saved | conversation={conversation_id} role={role}"
                )

                return message_id

        finally:
            conn.close()

    def get_messages(
        self,
        conversation_id: UUID,
    ) -> Sequence[MessageRow]:

        conn = get_connection()

        try:
            with conn.cursor() as curr:
                curr.execute(
                    """
                    SELECT
                        id,
                        role,
                        content,
                        created_at
                    FROM messages
                    WHERE conversation_id = %s
                    ORDER BY id ASC
                    """,
                    (conversation_id,),
                )

                rows = curr.fetchall()

                logger.debug(
                    f"Loaded {len(rows)} messages | conversation={conversation_id}"
                )

                return rows

        finally:
            conn.close()

    def get_messages_after_id(
        self,
        conversation_id: UUID,
        message_id: int,
    ) -> Sequence[MessageRow]:

        conn = get_connection()

        try:
            with conn.cursor() as curr:
                curr.execute(
                    """
                SELECT 
                    id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE conversation_id = %s
                AND id > %s
                ORDER BY id ASC
                """,
                    (conversation_id, message_id),
                )

                rows = curr.fetchall()

                logger.debug(
                    f"Loaded {len(rows)} unsummarized messages | conversation={conversation_id}"
                )

                return rows

        finally:
            conn.close()

    def get_latest_message_id(
        self,
        conversation_id: UUID,
    ) -> int:

        conn = get_connection()

        try:
            with conn.cursor() as curr:
                curr.execute(
                    """
                SELECT COALESCE(MAX(id), 0)
                FROM messages
                WHERE conversation_id = %s
                """,
                    (conversation_id,),
                )

                result = curr.fetchone()

                return result[0]

        finally:
            conn.close()

    def get_recent_messages(
        self, conversation_id: UUID, limit: int = 20
    ) -> Sequence[MessageRow]:
        conn = get_connection()

        try:
            with conn.cursor() as curr:
                curr.execute(
                    """
                SELECT
                    id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                    (conversation_id, limit),
                )

                rows = curr.fetchall()

                rows.reverse()

                logger.debug(
                    f"Loaded {len(rows)} recent messages | conversation={conversation_id}"
                )

                return rows

        finally:
            conn.close()
