from dataclasses import dataclass, field
from uuid import UUID

from langchain_core.messages import BaseMessage, SystemMessage

from app.repositories.summary_repository import SummaryRepository
from app.utils.logger import logger


@dataclass(frozen=True)
class SummaryContext:
    """
    The durable summary for one conversation, plus its watermark.

    last_summarized_message_id marks how far the summary covers, so the
    history builder knows where to start and the two sources never overlap.
    """

    messages: list[BaseMessage] = field(default_factory=list)
    last_summarized_message_id: int = 0


class SummaryContextBuilder:
    """
    Loads the durable conversation summary, if one exists.

    This only reads previously generated summary state — it never calls an
    LLM. Summary generation is handled out-of-band by SummarizationService.
    """

    def __init__(self, summary_repository: SummaryRepository) -> None:
        self.summary_repository = summary_repository

    def build(self, conversation_id: UUID) -> SummaryContext:
        """
        Read the summary state once and return both the summary message
        and its watermark.
        """
        state = self.summary_repository.get_summary_state(conversation_id)

        if state is None:
            return SummaryContext()

        summary, last_summarized_message_id = state

        if not summary:
            return SummaryContext(
                last_summarized_message_id=last_summarized_message_id,
            )

        logger.debug(
            "Summary context loaded | conversation=%s characters=%s through_message=%s",
            conversation_id,
            len(summary),
            last_summarized_message_id,
        )

        return SummaryContext(
            messages=[
                SystemMessage(
                    content=(
                        "Durable conversation memory from earlier in this "
                        "conversation:\n\n"
                        f"{summary}"
                    )
                )
            ],
            last_summarized_message_id=last_summarized_message_id,
        )
