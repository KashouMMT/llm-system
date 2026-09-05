import time
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.config.runtime_settings import RuntimeSettingsHolder
from app.config.settings import (
    SUMMARY_CHUNK_PROMPT,
    SUMMARY_MERGE_PROMPT,
)
from app.repositories.message_repository import Message, MessageRepository
from app.repositories.summary_repository import SummaryRepository, SummaryState
from app.utils.logger import logger


class SummarizationService:
    """
    Generates and persists durable conversation summaries.

    This is maintenance work, not part of answering a turn — every method
    here may issue its own LLM call and must only ever be awaited from a
    background task, never from the request/response path that produces
    the user-facing reply.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        message_repository: MessageRepository,
        summary_repository: SummaryRepository,
        settings: RuntimeSettingsHolder,
    ) -> None:
        self.llm = llm
        self.message_repository = message_repository
        self.summary_repository = summary_repository
        self.settings = settings

    @staticmethod
    def estimate_tokens(text: str) -> int:
        # Rough character-based estimate. Good enough for a threshold
        # check; do not rely on it anywhere precision matters.
        return len(text) // 4

    async def _get_unsummarized_messages(
        self,
        conversation_id: UUID,
        last_summarized_message_id: int,
    ) -> list[Message]:
        return list(
            await self.message_repository.get_messages_after_id(
                conversation_id=conversation_id,
                message_id=last_summarized_message_id,
            )
        )

    def _split_for_retention(
        self,
        rows: list[Message],
        min_retained: int,
    ) -> tuple[list[Message], list[Message]]:
        """
        Split the backlog into the part to summarize and the raw tail to keep.

        Folding every message leaves the next turn with the summary and
        nothing verbatim — the model loses the thread of what was just
        agreed and re-asks settled questions. Holding a tail back costs a
        little context and removes that cliff entirely.

        The tail is extended backwards to the nearest user message so it
        opens with a question rather than half of an answer.
        """
        if len(rows) <= min_retained:
            return [], rows

        boundary = len(rows) - min_retained

        while boundary > 0 and rows[boundary].role != "user":
            boundary -= 1

        if boundary == 0:
            # Aligning to a turn boundary consumed the whole backlog.
            # Progress matters more than alignment here: a watermark that
            # never advances is the failure this method exists to prevent.
            boundary = len(rows) - min_retained

        return rows[:boundary], rows[boundary:]

    def should_summarize(
        self,
        conversation_id: UUID,
        rows: list[Message],
    ) -> bool:
        if not rows:
            return False

        # One snapshot for the whole check: a change landing between the
        # two comparisons must not decide half of this answer.
        settings = self.settings.current

        if len(rows) >= settings.max_unsummarized_messages:
            logger.warning(
                "Unsummarized backlog exceeds hard limit | "
                "conversation=%s messages=%s limit=%s",
                conversation_id,
                len(rows),
                settings.max_unsummarized_messages,
            )
            return True

        combined_text = "\n".join(row.content for row in rows)
        estimated_tokens = self.estimate_tokens(combined_text)

        logger.debug(
            "Summary check | conversation=%s messages=%s estimated_tokens=%s",
            conversation_id,
            len(rows),
            estimated_tokens,
        )

        return estimated_tokens >= settings.summary_token_threshold

    async def _generate_chunk_summary(self, rows: list[Message]) -> str:
        conversation = "\n".join(f"{row.role}: {row.content}" for row in rows)

        prompt = SUMMARY_CHUNK_PROMPT.format(conversation=conversation)

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])

        return response.content

    async def _merge_summary(
        self,
        current_summary: str,
        chunk_summary: str,
    ) -> str:
        if not current_summary:
            # Nothing to merge with yet — the chunk summary is the whole
            # summary. Skips feeding an empty CURRENT SUMMARY into the
            # merge prompt on a conversation's first summarization.
            return chunk_summary

        # Asked for less than the hard cap on purpose: the cap is a backstop
        # for a model that ignored the budget, so it must not double as the
        # target. Room between the two is what keeps _cap_summary quiet.
        prompt = SUMMARY_MERGE_PROMPT.format(
            current_summary=current_summary,
            chunk_summary=chunk_summary,
            max_characters=int(self.settings.current.max_summary_chars * 0.75),
        )

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])

        return response.content

    async def summarize(
        self,
        conversation_id: UUID,
        state: SummaryState | None,
        rows: list[Message],
    ) -> None:
        """
        Fold `rows` into the durable summary.

        `state` and `rows` must come from the same read: the watermark in
        `state` is what the conditional advance is checked against, so a
        newer state paired with older rows would defeat that check.
        """
        if not rows:
            return

        start = time.perf_counter()

        current_summary = state.summary if state is not None else ""
        watermark = state.last_summarized_message_id if state is not None else 0

        chunk_summary = await self._generate_chunk_summary(rows)

        updated_summary = self._cap_summary(
            await self._merge_summary(
                current_summary=current_summary,
                chunk_summary=chunk_summary,
            ),
            conversation_id,
        )

        advanced = await self.summary_repository.save_summary_chunk_and_advance(
            conversation_id=conversation_id,
            start_message_id=rows[0].id,
            end_message_id=rows[-1].id,
            chunk_summary=chunk_summary,
            updated_summary=updated_summary,
            expected_last_summarized_message_id=watermark,
        )

        logger.info(
            "Conversation summarized | conversation=%s messages=%s "
            "advanced=%s elapsed=%.2fs",
            conversation_id,
            len(rows),
            advanced,
            time.perf_counter() - start,
        )

    def _cap_summary(self, summary: str, conversation_id: UUID) -> str:
        """
        Backstop for a merge prompt that ignored its length instruction.

        The summary exists to be cheaper than the transcript it replaces, so
        an unbounded one defeats its own purpose. Truncation is crude and
        loses the tail, but a summary that silently grows without limit is
        worse — and the warning is the signal to fix the prompt.
        """
        limit = self.settings.current.max_summary_chars

        if len(summary) <= limit:
            return summary

        logger.warning(
            "Summary exceeded cap and was truncated | "
            "conversation=%s characters=%s limit=%s",
            conversation_id,
            len(summary),
            limit,
        )

        return summary[:limit]

    async def trigger_if_needed(self, conversation_id: UUID) -> None:
        """
        Summarize this conversation only if it currently needs it.

        Intended to be called after every turn from a background task.
        Any failure here must never propagate into the chat response path —
        callers are expected to isolate errors around this call.
        """
        state = await self.summary_repository.get_summary_state(conversation_id)

        rows = await self._get_unsummarized_messages(
            conversation_id,
            state.last_summarized_message_id if state is not None else 0,
        )

        if not self.should_summarize(conversation_id, rows):
            return

        to_summarize, retained = self._split_for_retention(
            rows,
            self.settings.current.min_retained_raw_messages,
        )

        if not to_summarize:
            # RuntimeSettings forbids the configuration that causes this,
            # so reaching it means the invariant was bypassed somehow.
            logger.warning(
                "Summarization triggered with nothing to fold | "
                "conversation=%s backlog=%s retained=%s",
                conversation_id,
                len(rows),
                len(retained),
            )
            return

        logger.debug(
            "Summarizing backlog | conversation=%s folding=%s retained_raw=%s",
            conversation_id,
            len(to_summarize),
            len(retained),
        )

        await self.summarize(conversation_id, state, to_summarize)
