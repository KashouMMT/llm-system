import time
import uuid
from collections.abc import AsyncIterator
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.agent.graph import AgentGraph
from app.repositories.conversation_repository import ConversationRepository
from app.utils.logger import logger


class ChatService:
    """
    Application-level chat service.

    A turn is persisted only after the graph completes successfully and
    produces a final text response.
    """
    def __init__(
        self,
        agent_graph: AgentGraph,
        conversation_repository: ConversationRepository,
    ) -> None:
        self.agent_graph = agent_graph
        self.conversation_repository = conversation_repository

        logger.info("ChatService initialized")

    async def chat_stream(
        self,
        user_input: str,
        conversation_id: UUID,
    ) -> AsyncIterator[str]:
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
            async for event in self.agent_graph.stream(
                input_messages=input_messages,
                thread_id=str(conversation_id),
            ):
                logger.debug(
                    "Processing graph event | request=%s nodes=%s",
                    request_id,
                    list(event.keys()),
                )

                agent_update = event.get("agent")

                if not agent_update:
                    continue

                for message in agent_update.get("messages", []):
                    if not message.content:
                        continue

                    content = message.content
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

        except Exception:
            latency = time.perf_counter() - start

            logger.exception(
                "Chat request failed | request=%s conversation=%s elapsed=%.2fs",
                request_id,
                conversation_id,
                latency,
            )

            raise
