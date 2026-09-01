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
from app.repositories.summary_repository import SummaryRepository
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
    ) -> list[Message]:
        last_id = await self.summary_repository.get_last_summarized_message_id(
            conversation_id,
        )

        return list(
            await self.message_repository.get_messages_after_id(
                conversation_id=conversation_id,
                message_id=last_id,
            )
        )

    async def should_summarize(
        self,
        conversation_id: UUID,
        unsummarized_rows: list[Message] | None = None,
    ) -> bool:
        rows = (
            unsummarized_rows
            if unsummarized_rows is not None
            else await self._get_unsummarized_messages(conversation_id)
        )

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

        prompt = SUMMARY_MERGE_PROMPT.format(
            current_summary=current_summary,
            chunk_summary=chunk_summary,
        )

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])

        return response.content

    async def summarize(
        self,
        conversation_id: UUID,
        unsummarized_rows: list[Message] | None = None,
    ) -> None:
        """
        Summarize all currently unsummarized messages for one conversation.

        A no-op if there is nothing unsummarized. Callers that already
        fetched the rows should pass them to avoid a second identical query.
        """
        start = time.perf_counter()

        rows = (
            unsummarized_rows
            if unsummarized_rows is not None
            else await self._get_unsummarized_messages(conversation_id)
        )

        if not rows:
            return

        chunk_summary = await self._generate_chunk_summary(rows)

        current_summary = await self.summary_repository.get_current_summary(
            conversation_id,
        )

        updated_summary = await self._merge_summary(
            current_summary=current_summary,
            chunk_summary=chunk_summary,
        )

        start_message_id = rows[0].id
        end_message_id = rows[-1].id

        await self.summary_repository.save_summary_chunk_and_advance(
            conversation_id=conversation_id,
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            chunk_summary=chunk_summary,
            updated_summary=updated_summary,
        )

        elapsed = time.perf_counter() - start

        logger.info(
            "Conversation summarized | conversation=%s messages=%s elapsed=%.2fs",
            conversation_id,
            len(rows),
            elapsed,
        )

    async def trigger_if_needed(self, conversation_id: UUID) -> None:
        """
        Summarize this conversation only if it currently needs it.

        Intended to be called after every turn from a background task.
        Any failure here must never propagate into the chat response path —
        callers are expected to isolate errors around this call.
        """
        rows = await self._get_unsummarized_messages(conversation_id)

        if not await self.should_summarize(
            conversation_id,
            unsummarized_rows=rows,
        ):
            return

        await self.summarize(conversation_id, unsummarized_rows=rows)
