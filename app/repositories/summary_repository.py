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

    async def save_summary_chunk_and_advance(
        self,
        conversation_id: UUID,
        start_message_id: int,
        end_message_id: int,
        chunk_summary: str,
        updated_summary: str,
        expected_last_summarized_message_id: int,
    ) -> bool:
        """
        Save one summary chunk and advance the summary state atomically.

        Both writes commit together. If either fails, both roll back — so a
        crash mid-write can never leave last_summarized_message_id advanced
        without its corresponding chunk saved, or vice versa, which would
        otherwise cause the next run to re-summarize and duplicate a chunk.

        The advance is conditional on the watermark still being where the
        caller read it. If another process summarized the same range while
        this run was talking to the model, the whole transaction rolls back
        and this returns False rather than writing a duplicate chunk. The
        caller's work is simply discarded — the other run already did it.
        """
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
                WHERE conversation_summary_state.last_summarized_message_id
                      = %s
                """,
                (
                    conversation_id,
                    updated_summary,
                    end_message_id,
                    expected_last_summarized_message_id,
                ),
            )

            if cur.rowcount != 1:
                # Either the row already moved past our watermark, or the
                # INSERT collided with a concurrent first summarization.
                await conn.rollback()

                logger.info(
                    "Summary advance skipped, watermark moved | "
                    "conversation=%s expected=%s",
                    conversation_id,
                    expected_last_summarized_message_id,
                )

                return False

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

        logger.debug(
            "Summary chunk saved and state advanced | "
            "conversation=%s through_message=%s",
            conversation_id,
            end_message_id,
        )

        return True
