import asyncio
import time
from datetime import datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from app.documents.dates import JST
from app.documents.renderers.base import Renderer
from app.documents.renderers.text_renderer import TextRenderer
from app.documents.renderers.xlsx_renderer import XlsxRenderer
from app.documents.schemas_rirekisho import Rirekisho
from app.documents.schemas_shokumu import ShokumuKeirekisho
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.logger import logger

# These strings are sent to the model on every single call as part of the
# tool schema, alongside every field description in the corresponding
# schema. They are prompt text, not documentation — which is also why they
# live here rather than in anna.txt, where they would be paid for even on
# turns that have nothing to do with documents.
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

_SHOKUMU_KEIREKISHO_DESCRIPTION = """\
Generate a 職務経歴書 (shokumu keirekisho, detailed work history) file the
user can download.

Call this ONLY when all of the following are true:
- The user has explicitly asked for their 職務経歴書 to be created.
- You have confirmed every required field with the user in conversation.
- You are not guessing, inferring, or filling in any value yourself.

Do NOT call this to draft, preview, or discuss a 職務経歴書 — write that as
a normal reply instead. This tool produces a finished file, so calling it
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

    def _make_generate_tool(
        *,
        name: str,
        description: str,
        schema_cls: type[BaseModel],
        renderer: Renderer,
        document_type: str,
        display_name: str,
        filename_prefix: str,
    ) -> BaseTool:
        """
        One document type's generate_* tool.

        Every document type validates, renders, stores, and records its
        file the same way — only the schema, template, and document_type
        differ. Factored out once a second document type made the
        duplication real rather than hypothetical.
        """

        async def generate(config: RunnableConfig, **fields: object) -> str:
            start = time.perf_counter()

            # Validated a second time on purpose. LangChain already checked
            # the arguments against args_schema, but this is what turns a
            # dict back into a typed object, and it is the only guarantee
            # that what gets rendered is what passed validation.
            data = schema_cls(**fields)

            # Identity comes from the run configuration, never from the
            # tool arguments. A conversation id supplied by the model could
            # name a conversation belonging to someone else.
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
                "Tool started | tool=%s conversation=%s",
                name,
                conversation_id,
            )

            content = await asyncio.to_thread(renderer.render, data)

            # Bytes first, row second. The reverse order can produce a row
            # pointing at a file that does not exist, which the user meets
            # as a failed download; this order can only leave an
            # unreferenced blob.
            storage_key = await storage.write(
                content,
                extension=renderer.extension,
            )

            stamp = datetime.now(tz=JST).strftime("%Y%m%d_%H%M%S")
            filename = f"{filename_prefix}_{stamp}.{renderer.extension}"

            await file_repository.create(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                user_id=conversation.user_id,
                document_type=document_type,
                filename=filename,
                storage_key=storage_key,
                content_type=renderer.content_type,
                size_bytes=len(content),
            )

            logger.info(
                "Tool completed | tool=%s conversation=%s file=%s bytes=%s "
                "elapsed=%.4fs",
                name,
                conversation_id,
                filename,
                len(content),
                time.perf_counter() - start,
            )

            # Deliberately terse, and carries no identifier. Everything
            # here is read by the model and may end up quoted in its
            # reply; the download link comes from the message attachment,
            # not from this text.
            return (
                f"{display_name} generated successfully as {filename}. "
                "It is attached to this message for the user to download. "
                "Tell the user it is ready — do not repeat its contents."
            )

        return StructuredTool.from_function(
            coroutine=generate,
            name=name,
            description=description,
            args_schema=schema_cls,
        )

    return [
        _make_generate_tool(
            name="generate_rirekisho",
            description=_RIREKISHO_DESCRIPTION,
            schema_cls=Rirekisho,
            renderer=XlsxRenderer(),
            document_type="rirekisho",
            display_name="履歴書",
            filename_prefix="rirekisho",
        ),
        _make_generate_tool(
            name="generate_shokumu_keirekisho",
            description=_SHOKUMU_KEIREKISHO_DESCRIPTION,
            schema_cls=ShokumuKeirekisho,
            renderer=TextRenderer("shokumu_keirekisho.txt"),
            document_type="shokumu_keirekisho",
            display_name="職務経歴書",
            filename_prefix="shokumu_keirekisho",
        ),
    ]
