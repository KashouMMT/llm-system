from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config.settings import MAX_USER_INPUT_CHARS
from app.runtime.application import Application
from app.utils.logger import logger


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_USER_INPUT_CHARS)


def create_api(application: Application) -> FastAPI:

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/conversations")
    async def create_conversation():

        conversation_id = application.conversation_repository.create_conversation()

        return {
            "id": str(conversation_id),
        }

    @app.get("/conversations")
    async def get_conversations():

        conversations = application.conversation_repository.get_conversations()

        return [
            {
                "id": str(row[0]),
                "title": row[1],
                "created_at": row[2],
                "updated_at": row[3],
            }
            for row in conversations
        ]

    @app.get("/conversations/{conversation_id}/messages")
    async def get_messages(conversation_id: UUID):

        exists = application.conversation_repository.exists(conversation_id)

        if not exists:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )

        messages = application.message_repository.get_messages(conversation_id)

        return [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3],
            }
            for row in messages
        ]

    @app.post("/conversations/{conversation_id}/chat/stream")
    async def chat_stream(conversation_id: UUID, request: ChatRequest):

        exists = application.conversation_repository.exists(conversation_id)

        if not exists:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )

        async def generator():

            if application.chat_service is None:
                raise RuntimeError("Application has not been initialized")

            try:
                async for chunk in application.chat_service.chat_stream(
                    user_input=request.message,
                    conversation_id=conversation_id,
                ):
                    yield chunk

            except Exception:  # noqa: BLE001
                # Headers are already sent, so HTTPException cannot apply here.
                # Emit a visible marker so the client does not mistake a
                # truncated stream for a complete answer.
                logger.exception(
                    "Chat stream failed | conversation=%s",
                    conversation_id,
                )
                yield "\n\n[error] The response was interrupted. Please try again."

        return StreamingResponse(
            generator(),
            media_type="text/plain",
        )

    return app
