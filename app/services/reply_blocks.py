"""
Deterministic Markdown a tool puts into the reply, bypassing the model.

A tool's return value goes to the model, and a model asked to relay a
40-row table can drop a row or alter a number. So a tool whose output must
reach the user exactly — a scan's result table — publishes it here instead,
and returns only a short summary for the model to comment on.

ChatService attaches a writer for the assistant message it is generating;
the writer appends the block to the same buffer and delta stream the
model's tokens use. That is why no frontend change is needed, and why the
block lands in the saved message exactly where it appeared on screen.

Framework-free on purpose. LangGraph's custom stream writer would do the
same job, but it would tie how a reply is composed to LangGraph's
streaming API; this is a dict and a callable.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.utils.logger import logger

BlockWriter = Callable[[str], None]


class ReplyBlocks:
    def __init__(self) -> None:
        self._writers: dict[int, BlockWriter] = {}

    @contextmanager
    def attach(self, assistant_message_id: int, writer: BlockWriter) -> Iterator[None]:
        """Route blocks for this message to `writer` for the duration of a
        generation. Detached on exit however the generation ends, so a
        late publish cannot write into a message that is already saved."""
        self._writers[assistant_message_id] = writer
        try:
            yield
        finally:
            self._writers.pop(assistant_message_id, None)

    def publish(self, assistant_message_id: int, markdown: str) -> bool:
        """
        Put `markdown` into the reply being generated for this message.

        Returns False when no generation is attached — the caller must then
        decide what the user sees instead, never assume it was shown. Call
        from the event loop (an async tool), not a worker thread: the
        writer publishes to the event bus directly.
        """
        writer = self._writers.get(assistant_message_id)

        if writer is None:
            logger.warning(
                "Reply block dropped, no generation attached | message=%s chars=%s",
                assistant_message_id,
                len(markdown),
            )
            return False

        writer(markdown)
        return True
