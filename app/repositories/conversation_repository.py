from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from app.database.connection import get_connection
from app.utils.logger import logger

ConversationRow = tuple[
    UUID,
    str,
    datetime,
    datetime,
]


class ConversationRepository:
    def create_conversation(
        self,
        title: str = "New Conversation",
    ) -> UUID:
        conversation_id = uuid4()

        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (
                        id,
                        title
                    )
                    VALUES (%s, %s)
                    """,
                    (
                        conversation_id,
                        title,
                    ),
                )

            conn.commit()

            logger.info(
                "Conversation created | id=%s",
                conversation_id,
            )

            return conversation_id

        finally:
            conn.close()

    def get_conversation(
        self,
        conversation_id: UUID,
    ) -> ConversationRow | None:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        title,
                        created_at,
                        updated_at
                    FROM conversations
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )

                return cur.fetchone()

        finally:
            conn.close()

    def get_conversations(self) -> Sequence[ConversationRow]:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        title,
                        created_at,
                        updated_at
                    FROM conversations
                    ORDER BY updated_at DESC
                    """
                )

                rows = cur.fetchall()

                logger.debug(
                    "Loaded %s conversations",
                    len(rows),
                )

                return rows

        finally:
            conn.close()

    def exists(
        self,
        conversation_id: UUID,
    ) -> bool:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM conversations
                        WHERE id = %s
                    )
                    """,
                    (conversation_id,),
                )

                result = cur.fetchone()

                return bool(result[0])

        finally:
            conn.close()

    def save_completed_turn(
        self,
        conversation_id: UUID,
        user_content: str,
        assistant_content: str,
    ) -> tuple[int, int]:
        """
        Persist one completed conversation turn atomically.

        If either message write or the conversation timestamp update fails,
        PostgreSQL rolls back all writes from this method.
        """
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
                        "user",
                        user_content,
                    ),
                )

                user_message_id = cur.fetchone()[0]

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
                        "assistant",
                        assistant_content,
                    ),
                )

                assistant_message_id = cur.fetchone()[0]

                cur.execute(
                    """
                    UPDATE conversations
                    SET updated_at = NOW()
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )

                if cur.rowcount != 1:
                    raise ValueError(f"Conversation not found: {conversation_id}")

            conn.commit()

            logger.debug(
                "Completed turn saved | conversation=%s user_message=%s "
                "assistant_message=%s",
                conversation_id,
                user_message_id,
                assistant_message_id,
            )

            return (
                user_message_id,
                assistant_message_id,
            )

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def update_title(
        self,
        conversation_id: UUID,
        title: str,
    ) -> None:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
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

            conn.commit()

            logger.debug(
                "Conversation title updated | id=%s",
                conversation_id,
            )

        finally:
            conn.close()

    def touch(
        self,
        conversation_id: UUID,
    ) -> None:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET updated_at = NOW()
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )

            conn.commit()

        finally:
            conn.close()

    def delete_conversation(
        self,
        conversation_id: UUID,
    ) -> None:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM conversations
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )

            conn.commit()

            logger.info(
                "Conversation deleted | id=%s",
                conversation_id,
            )

        finally:
            conn.close()
