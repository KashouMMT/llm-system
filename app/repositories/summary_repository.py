from dataclasses import dataclass
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.utils.logger import logger


@dataclass(frozen=True)
class SummaryState:
    """
    The durable summary for one conversation and how far it covers.

    last_summarized_message_id is the watermark the history builder starts
    from, so the summary and the transcript never overlap.
    """

    summary: str
    last_summarized_message_id: int


class SummaryRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_summary_state(
        self,
        conversation_id: UUID,
    ) -> SummaryState | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(SummaryState)) as cur,
        ):
            await cur.execute(
                """
                SELECT
                    summary,
                    last_summarized_message_id
                FROM conversation_summary_state
                WHERE conversation_id = %s
                """,
                (conversation_id,),
            )

            return await cur.fetchone()

    async def get_current_summary(
        self,
        conversation_id: UUID,
    ) -> str:
        state = await self.get_summary_state(conversation_id)

        if state is None:
            return ""

        return state.summary

    async def get_last_summarized_message_id(
        self,
        conversation_id: UUID,
    ) -> int:
        state = await self.get_summary_state(conversation_id)

        if state is None:
            return 0

        return state.last_summarized_message_id

    async def upsert_summary_state(
        self,
        conversation_id: UUID,
        summary: str,
        last_summarized_message_id: int,
    ) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
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

        logger.debug(
            "Summary state updated | conversation=%s",
            conversation_id,
        )

    async def save_summary_chunk(
        self,
        conversation_id: UUID,
        start_message_id: int,
        end_message_id: int,
        summary: str,
    ) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
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

        logger.debug(
            "Summary chunk saved | conversation=%s",
            conversation_id,
        )

    async def save_summary_chunk_and_advance(
        self,
        conversation_id: UUID,
        start_message_id: int,
        end_message_id: int,
        chunk_summary: str,
        updated_summary: str,
    ) -> None:
        """
        Save one summary chunk and advance the summary state atomically.

        Both writes commit together. If either fails, both roll back — so a
        crash mid-write can never leave last_summarized_message_id advanced
        without its corresponding chunk saved, or vice versa, which would
        otherwise cause the next run to re-summarize and duplicate a chunk.
        """
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                INSERT INTO conversation_summaries (
                    conversation_id,
                    start_message_id,
                    end_message_id,
                    summary
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    start_message_id,
                    end_message_id,
                    chunk_summary,
                ),
            )

            await cur.execute(
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
                    updated_summary,
                    end_message_id,
                ),
            )

        logger.debug(
            "Summary chunk saved and state advanced | "
            "conversation=%s through_message=%s",
            conversation_id,
            end_message_id,
        )
