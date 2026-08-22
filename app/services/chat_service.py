import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.agent.graph import AgentGraph
from app.config.settings import MAX_USER_INPUT_CHARS
from app.repositories.conversation_repository import ConversationRepository
from app.services.summarization_service import SummarizationService
from app.utils.logger import logger


class ChatService:
    """
    Application-level chat service.

    A turn is persisted only after the graph completes successfully and
    produces a final text response. Summarization runs afterward, out of
    band, so it never delays the response.
    """

    def __init__(
        self,
        agent_graph: AgentGraph,
        conversation_repository: ConversationRepository,
        summarization_service: SummarizationService,
    ) -> None:
        self.agent_graph = agent_graph
        self.conversation_repository = conversation_repository
        self.summarization_service = summarization_service

        self._summarizing: set[UUID] = set()
        self._background_tasks: set[asyncio.Task] = set()

        logger.info("ChatService initialized")

    async def chat_stream(
        self,
        user_input: str,
        conversation_id: UUID,
    ) -> AsyncIterator[str]:
        
        user_input = user_input.strip()

        if not user_input:
            raise ValueError("Message must not be empty.")

        if len(user_input) > MAX_USER_INPUT_CHARS:
            raise ValueError(
                f"Message exceeds {MAX_USER_INPUT_CHARS} characters "
                f"(got {len(user_input)})."
            )
        
        request_id = uuid.uuid4().hex[:8]

        logger.info(
            "Chat request started | request=%s conversation=%s",
            request_id,
            conversation_id,
        )

        start = time.perf_counter()

        input_messages = [
            HumanMessage(content=user_input),
        ]

        response_buffer: list[str] = []

        try:
            async for message_chunk, metadata in self.agent_graph.stream(
                input_messages=input_messages,
                thread_id=str(conversation_id),
            ):
                if metadata.get("langgraph_node") != "agent":
                    continue

                content = message_chunk.content

                if not content or not isinstance(content, str):
                    continue

                response_buffer.append(content)

                yield content

            response_text = "".join(response_buffer)

            latency = time.perf_counter() - start

            logger.info(
                "Chat request completed | request=%s conversation=%s "
                "latency=%.2fs response_chars=%s",
                request_id,
                conversation_id,
                latency,
                len(response_text),
            )

            if not response_text:
                logger.warning(
                    "Successful graph execution returned no final text | "
                    "request=%s conversation=%s",
                    request_id,
                    conversation_id,
                )
                return

            self.conversation_repository.save_completed_turn(
                conversation_id=conversation_id,
                user_content=user_input,
                assistant_content=response_text,
            )

            self._schedule_summarization(conversation_id)

        except Exception:
            latency = time.perf_counter() - start

            logger.exception(
                "Chat request failed | request=%s conversation=%s elapsed=%.2fs",
                request_id,
                conversation_id,
                latency,
            )

            raise

    def _schedule_summarization(self, conversation_id: UUID) -> None:
        """
        Kick off summarization in the background, if not already running
        for this conversation.

        Never awaited by the caller — it must not add latency to the
        response the user just received.
        """
        if conversation_id in self._summarizing:
            return

        self._summarizing.add(conversation_id)

        task = asyncio.create_task(
            self._run_summarization(conversation_id),
        )

        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_summarization(self, conversation_id: UUID) -> None:
        try:
            await self.summarization_service.trigger_if_needed(
                conversation_id,
            )

        except Exception:  # noqa: BLE001
            logger.exception(
                "Background summarization failed | conversation=%s",
                conversation_id,
            )

        finally:
            self._summarizing.discard(conversation_id)
