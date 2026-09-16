import asyncio
import time
from datetime import datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from app.plugins.recruitment import prompts
from app.plugins.recruitment.renderers.base import Renderer
from app.plugins.recruitment.renderers.docx_renderer import DocxRenderer
from app.plugins.recruitment.renderers.xlsx_renderer import XlsxRenderer
from app.plugins.recruitment.schemas_rirekisho import Rirekisho
from app.plugins.recruitment.schemas_shokumu import ShokumuKeirekisho
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.file_repository import FileRepository
from app.storage.base import FileStorage
from app.utils.jst import JST
from app.utils.logger import logger


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
                origin="generated",
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

            return prompts.GENERATED.format(
                display_name=display_name,
                filename=filename,
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
            description=prompts.RIREKISHO_DESCRIPTION,
            schema_cls=Rirekisho,
            renderer=XlsxRenderer(),
            document_type="rirekisho",
            display_name="履歴書",
            filename_prefix="rirekisho",
        ),
        _make_generate_tool(
            name="generate_shokumu_keirekisho",
            description=prompts.SHOKUMU_KEIREKISHO_DESCRIPTION,
            schema_cls=ShokumuKeirekisho,
            renderer=DocxRenderer(),
            document_type="shokumu_keirekisho",
            display_name="職務経歴書",
            filename_prefix="shokumu_keirekisho",
        ),
    ]
