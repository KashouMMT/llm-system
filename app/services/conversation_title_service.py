import time
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.config.runtime_settings import RuntimeSettingsHolder
from app.config.settings import TITLE_MAX_CHARS
from app.llm.system_prompt import load_title_prompt
from app.repositories.conversation_repository import ConversationRepository
from app.runtime.event_bus import EVENT_CONVERSATION_UPDATED, Event, EventBus
from app.utils.logger import logger

# The title every conversation is created with. The auto-title runs only
# while this is still in place, so a manual rename or a second turn does not
# trigger a re-title. Must match the column default in
# ConversationRepository / init_db.py.
PLACEHOLDER_TITLE = "New Conversation"

# A model given "reply with the title alone" still sometimes wraps the
# answer. Stripped from the front before the length cap is applied.
_LABEL_PREFIXES = ("title:", "conversation title:", "titre:", "タイトル:")


class ConversationTitleService:
    """
    Names a conversation from its first user message.

    Out-of-band work, like SummarizationService: it issues its own LLM call
    and must only be awaited from a background task, never from the send
    path that produces the user-facing reply. Any failure leaves the
    placeholder title untouched and is logged — a conversation keeping the
    generic name is not worth failing or delaying a turn over.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        conversation_repository: ConversationRepository,
        event_bus: EventBus,
        settings: RuntimeSettingsHolder,
    ) -> None:
        self.llm = llm
        self.conversation_repository = conversation_repository
        self.event_bus = event_bus
        self.settings = settings

    async def generate_and_store(
        self,
        conversation_id: UUID,
        first_user_message: str,
    ) -> None:
        """
        Replace the placeholder title with an LLM-generated one.

        Re-reads the conversation and returns early unless its title is
        still the placeholder. That guard is what makes this safe to call
        after every turn rather than only the first: a titled conversation
        costs one indexed SELECT and nothing else, and two calls racing on
        a new conversation converge on a single write.
        """
        start = time.perf_counter()

        conversation = await self.conversation_repository.get_conversation(
            conversation_id,
        )

        if conversation is None:
            return

        if conversation.title != PLACEHOLDER_TITLE:
            logger.debug(
                "Title generation skipped, already named | conversation=%s",
                conversation_id,
            )
            return

        # str.replace, not str.format: the user's message is substituted
        # verbatim, and a stray brace in it must not raise.
        prompt = load_title_prompt(
            self.settings.current.system_prompt_name,
        ).replace("{message}", first_user_message)

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        except Exception:  # noqa: BLE001
            logger.exception(
                "Title generation LLM call failed | conversation=%s",
                conversation_id,
            )
            return

        title = self._clean(response.content)

        if not title:
            logger.warning(
                "Title generation produced nothing usable | conversation=%s",
                conversation_id,
            )
            return

        await self.conversation_repository.update_title(conversation_id, title)

        self.event_bus.publish(
            Event(
                type=EVENT_CONVERSATION_UPDATED,
                conversation_id=conversation_id,
                payload={"conversation_id": str(conversation_id)},
            )
        )

        logger.info(
            "Conversation titled | conversation=%s title=%r elapsed=%.2fs",
            conversation_id,
            title,
            time.perf_counter() - start,
        )

    @staticmethod
    def _clean(raw: object) -> str:
        """
        Reduce a model reply to a bare title: one line, no wrapping quotes
        or label prefix, capped at TITLE_MAX_CHARS.
        """
        if not isinstance(raw, str):
            return ""

        text = " ".join(raw.split())

        # Prefix then quotes then prefix again: covers both `Title: "x"` and
        # `"Title: x"` without a parsing loop.
        text = _strip_label_prefix(text).strip("\"'“”「」").strip()
        text = _strip_label_prefix(text).strip()

        if len(text) > TITLE_MAX_CHARS:
            text = text[:TITLE_MAX_CHARS].rstrip()

        return text


def _strip_label_prefix(text: str) -> str:
    lowered = text.lower()

    for prefix in _LABEL_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()

    return text
