import asyncio
import time
from datetime import datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

from app.documents.dates import JST
from app.documents.renderers.base import Renderer
from app.documents.renderers.text_renderer import TextRenderer
from app.documents.schemas import Rirekisho
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.logger import logger

# This string is sent to the model on every single call as part of the tool
# schema, alongside every field description in Rirekisho. It is prompt text,
# not documentation — which is also why it lives here rather than in
# anna.txt, where it would be paid for even on turns that have nothing to do
# with documents.
_RIREKISHO_DESCRIPTION = """\
Generate a 履歴書 (rirekisho) file the user can download.

Call this ONLY when all of the following are true:
- The user has explicitly asked for their 履歴書 to be created.
- You have confirmed every required field with the user in conversation.
- You are not guessing, inferring, or filling in any value yourself.

Do NOT call this to draft, preview, or discuss a 履歴書 — write that as a
normal reply instead. This tool produces a finished file, so calling it
early produces a document with wrong information in it.

If a required field is missing, do not call this tool. Ask the user for the
missing information first.
"""


def make_document_tools(
    storage: FileStorage,
    file_repository: FileRepository,
    conversation_repository: ConversationRepository,
) -> list[BaseTool]:
    """
    Build the document tools with their dependencies bound in.

    A closure factory rather than module-level functions, for the same
    reason as make_current_user in app/authentication/dependencies.py: a
    tool needs storage and repositories, and reaching for module globals to
    get them makes the graph impossible to construct twice.
    """
    rirekisho_renderer: Renderer = TextRenderer("rirekisho.txt")

    async def generate_rirekisho(config: RunnableConfig, **fields: object) -> str:
        start = time.perf_counter()

        # Validated a second time on purpose. LangChain already checked the
        # arguments against args_schema, but this is what turns a dict back
        # into a typed object, and it is the only guarantee that what gets
        # rendered is what passed validation.
        data = Rirekisho(**fields)

        # Identity comes from the run configuration, never from the tool
        # arguments. A conversation id supplied by the model could name a
        # conversation belonging to someone else.
        configurable = config.get("configurable", {})

        conversation_id = UUID(configurable["thread_id"])
        assistant_message_id = configurable.get("assistant_message_id")

        if assistant_message_id is None:
            raise RuntimeError(
                "assistant_message_id is missing from the run config; "
                "a generated file cannot be attached to a message."
            )

        conversation = await conversation_repository.get_conversation(
            conversation_id,
        )

        if conversation is None:
            raise RuntimeError(f"Conversation not found: {conversation_id}")

        logger.info(
            "Tool started | tool=generate_rirekisho conversation=%s",
            conversation_id,
        )

        content = await asyncio.to_thread(rirekisho_renderer.render, data)

        # Bytes first, row second. The reverse order can produce a row
        # pointing at a file that does not exist, which the user meets as a
        # failed download; this order can only leave an unreferenced blob.
        storage_key = await storage.write(
            content,
            extension=rirekisho_renderer.extension,
        )

        stamp = datetime.now(tz=JST).strftime("%Y%m%d_%H%M%S")
        filename = f"rirekisho_{stamp}.{rirekisho_renderer.extension}"

        await file_repository.create(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            user_id=conversation.user_id,
            document_type="rirekisho",
            filename=filename,
            storage_key=storage_key,
            content_type=rirekisho_renderer.content_type,
            size_bytes=len(content),
        )

        logger.info(
            "Tool completed | tool=generate_rirekisho conversation=%s "
            "file=%s bytes=%s elapsed=%.4fs",
            conversation_id,
            filename,
            len(content),
            time.perf_counter() - start,
        )

        # Deliberately terse, and carries no identifier. Everything here is
        # read by the model and may end up quoted in its reply; the download
        # link comes from the message attachment, not from this text.
        return (
            f"履歴書 generated successfully as {filename}. "
            "It is attached to this message for the user to download. "
            "Tell the user it is ready — do not repeat its contents."
        )

    return [
        StructuredTool.from_function(
            coroutine=generate_rirekisho,
            name="generate_rirekisho",
            description=_RIREKISHO_DESCRIPTION,
            args_schema=Rirekisho,
        )
    ]
