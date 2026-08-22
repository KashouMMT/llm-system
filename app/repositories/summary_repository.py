from uuid import UUID

from app.database.connection import get_connection
from app.utils.logger import logger

SummaryStateRow = tuple[
    str,
    int,
]

SummaryChunkRow = tuple[
    int,
    UUID,
    int,
    int,
    str,
]


class SummaryRepository:
    
    def get_summary_state(
        self, 
        conversation_id: UUID
    ) -> SummaryStateRow | None:

        conn = get_connection()

        try:
            with conn.cursor() as curr:
                curr.execute(
                    """
                    SELECT 
                        summary,
                        last_summarized_message_id
                    FROM conversation_summary_state
                    WHERE conversation_id = %s
                """,
                    (conversation_id,),
                )

                return curr.fetchone()

        finally:
            conn.close()

    def get_current_summary(
        self,
        conversation_id: UUID,
    ) -> str:

        state = self.get_summary_state(conversation_id)

        if state is None:
            return ""

        summary, _ = state

        return summary

    def get_last_summarized_message_id(
        self, 
        conversation_id: UUID
    ) -> int:

        state = self.get_summary_state(conversation_id)

        if state is None:
            return 0

        _, last_message_id = state

        return last_message_id

    def upsert_summary_state(
        self, 
        conversation_id: UUID, 
        summary: str, 
        last_summarized_message_id: int
    ) -> None:

        conn = get_connection()

        try:
            with conn.cursor() as curr:
                
                curr.execute(
                    """
                    INSERT INTO conversation_summary_state (
                        conversation_id,
                        summary,
                        last_summarized_message_id
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (conversation_id)
                    DO UPDATE SET
                        summary = EXCLUDED.summary,
                        last_summarized_message_id = 
                            EXCLUDED.last_summarized_message_id,
                        updated_at = NOW()
                """,
                    (
                        conversation_id,
                        summary,
                        last_summarized_message_id,
                    ),
                )

                conn.commit()

                logger.debug(f"Summary state updated | conversation={conversation_id}")

        finally:
            conn.close()

    def save_summary_chunk(
        self,
        conversation_id: UUID,
        start_message_id: int,
        end_message_id: int,
        summary: str,
    ) -> None:

        conn = get_connection()

        try:
            with conn.cursor() as curr:
                curr.execute(
                    """
                INSERT INTO conversation_summaries (
                    conversation_id,
                    start_message_id,
                    end_message_id,
                    summary
                )
                VALUES (%s, %s, %s, %s)
                """,
                    (conversation_id, start_message_id, end_message_id, summary),
                )

                conn.commit()

                logger.debug(f"Summary chunk saved | conversation={conversation_id}")

        finally:
            conn.close()
