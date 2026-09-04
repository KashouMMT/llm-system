import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.authentication.authorization import is_admin
from app.authentication.dependencies import make_current_user, make_require_admin
from app.authentication.models import User
from app.config.settings import (
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    MAX_USER_INPUT_CHARS,
    SESSION_COOKIE_NAME,
)
from app.repositories.conversation_repository import Conversation
from app.repositories.message_repository import TurnLookup
from app.runtime.application import Application
from app.runtime.event_bus import Event
from app.services.chat_service import ConversationHeldError
from app.utils.logger import logger

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # nginx buffers proxied responses by default, which would hold tokens
    # back until the whole response finished.
    "X-Accel-Buffering": "no",
}


class SendMessageRequest(BaseModel):
    # Client-generated so a retried send is recognisable as the same send.
    client_message_id: UUID
    message: str = Field(min_length=1, max_length=MAX_USER_INPUT_CHARS)


class LoginRequest(BaseModel):
    # max_length caps bound the argon2 input; a password longer than this is
    # not a real password.
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


def format_sse(event: Event) -> str:
    lines = []

    if event.id is not None:
        lines.append(f"id: {event.id}")

    lines.append(f"event: {event.type}")
    lines.append(f"data: {json.dumps(event.to_wire())}")

    return "\n".join(lines) + "\n\n"


def create_api(application: Application) -> FastAPI:

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    current_user = make_current_user(application)
    require_admin = make_require_admin(current_user)

    async def require_conversation(
        conversation_id: UUID,
        user: Annotated[User, Depends(current_user)],
    ) -> Conversation:
        conversation = await application.conversation_repository.get_conversation(
            conversation_id,
        )

        # 404, not 403, for another user's conversation: do not confirm that
        # an id they cannot see exists.
        if conversation is None or (
            conversation.user_id != user.id and not is_admin(user)
        ):
            raise HTTPException(status_code=404, detail="Conversation not found")

        return conversation

    # ---- auth -----------------------------------------------------------

    @app.post("/auth/login")
    async def login(body: LoginRequest, response: Response):
        result = await application.auth_service.login(body.username, body.password)

        if result is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password",
            )

        user, token, expires_at = result

        max_age = max(
            0,
            int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        )

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=max_age,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
            path="/",
        )

        return {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
        }

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE_NAME)

        await application.auth_service.logout(token)

        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path="/",
            httponly=True,
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
        )

    @app.get("/auth/me")
    async def me(user: Annotated[User, Depends(current_user)]):
        return {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
        }

    # ---- conversations ------------------------------------------------------

    @app.post("/conversations")
    async def create_conversation(user: Annotated[User, Depends(current_user)]):
        conversation_id = await application.conversation_repository.create_conversation(
            user_id=user.id,
        )

        return {"id": str(conversation_id)}

    @app.get("/conversations")
    async def get_conversations(user: Annotated[User, Depends(current_user)]):
        conversations = await application.conversation_repository.get_conversations(
            user.id,
        )

        return [
            {
                "id": str(conversation.id),
                "title": conversation.title,
                "status": conversation.status,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
            }
            for conversation in conversations
        ]

    @app.get("/conversations/{conversation_id}/messages")
    async def get_messages(
        conversation: Annotated[Conversation, Depends(require_conversation)],
    ):
        messages = await application.message_repository.get_messages(
            conversation.id,
        )

        # One query for the whole transcript rather than one per message.
        files = await application.file_repository.get_by_message_ids(
            [message.id for message in messages],
        )

        attachments: dict[int, list[dict[str, Any]]] = {}

        for file in files:
            attachments.setdefault(file.message_id, []).append(
                {
                    "id": str(file.id),
                    "document_type": file.document_type,
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "size_bytes": file.size_bytes,
                    "created_at": file.created_at,
                }
            )

        return [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
                "status": message.status,
                # storage_key is deliberately absent: the client addresses a
                # file by its id, and where the bytes actually live is not
                # its business.
                "attachments": attachments.get(message.id, []),
            }
            for message in messages
        ]

    @app.post(
        "/conversations/{conversation_id}/messages",
        status_code=202,
    )
    async def send_message(
        request: SendMessageRequest,
        conversation: Annotated[Conversation, Depends(require_conversation)],
        user: Annotated[User, Depends(current_user)],
    ):
        """
        Open a turn and start generating it in the background.
        """
        conversation_id = conversation.id

        existing = await application.message_repository.get_turn_by_client_message_id(
            request.client_message_id,
        )

        if existing is not None:
            return _existing_turn_response(existing, conversation_id)

        if not application.conversation_lock.try_acquire(conversation_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "generation_in_progress",
                    "assistant_message_id": (
                        application.conversation_lock.in_flight_message_id(
                            conversation_id,
                        )
                    ),
                },
            )

        try:
            turn = await application.chat_service.begin_turn(
                conversation_id=conversation_id,
                user=user,
                user_input=request.message,
                client_message_id=request.client_message_id,
            )

        except psycopg.errors.UniqueViolation:
            application.conversation_lock.release(conversation_id)

            existing = (
                await application.message_repository.get_turn_by_client_message_id(
                    request.client_message_id,
                )
            )

            if existing is None:
                raise

            return _existing_turn_response(existing, conversation_id)

        except ConversationHeldError as error:
            application.conversation_lock.release(conversation_id)

            raise HTTPException(
                status_code=423,
                detail="This conversation is on hold pending administrator review.",
            ) from error

        except ValueError as error:
            application.conversation_lock.release(conversation_id)

            raise HTTPException(status_code=422, detail=str(error)) from error

        except Exception:
            application.conversation_lock.release(conversation_id)

            raise

        application.spawn(
            application.chat_service.generate(
                conversation_id=conversation_id,
                user_message_id=turn.user_message_id,
                assistant_message_id=turn.assistant_message_id,
                user_input=request.message,
            )
        )

        return {
            "user_message_id": turn.user_message_id,
            "assistant_message_id": turn.assistant_message_id,
        }

    # ---- files -------------------------------------------------------

    @app.get("/files/{file_id}")
    async def download_file(
        file_id: UUID,
        user: Annotated[User, Depends(current_user)],
    ):
        record = await application.file_repository.get_by_id(file_id)

        # 404 rather than 403 for someone else's file, matching
        # require_conversation: do not confirm that an id they cannot see
        # exists.
        if record is None or (record.user_id != user.id and not is_admin(user)):
            raise HTTPException(status_code=404, detail="File not found")

        try:
            content = await application.file_storage.read(record.storage_key)

        except FileNotFoundError as error:
            # A row with no bytes is our inconsistency, not a bad request —
            # so it is logged as an error even though the caller gets 404.
            logger.error(
                "Generated file row has no bytes | file=%s key=%s",
                record.id,
                record.storage_key,
            )

            raise HTTPException(
                status_code=404,
                detail="File not found",
            ) from error

        return Response(
            content=content,
            media_type=record.content_type,
            headers={"Content-Disposition": _attachment_header(record.filename)},
        )

    @app.get("/events")
    async def events(
        request: Request,
        conversation: Annotated[Conversation, Depends(require_conversation)],
    ):
        """
        Server-sent events for one conversation.
        """
        conversation_id = conversation.id

        async def generator() -> AsyncIterator[str]:
            async with application.event_bus.subscribe(
                conversation_id,
            ) as subscription:
                # Browsers honour this as the reconnect delay.
                yield "retry: 3000\n\n"

                while True:
                    event = await subscription.next_event(
                        timeout=application.runtime_settings.current.sse_heartbeat_seconds,
                    )

                    if subscription.overflowed:
                        logger.warning(
                            "Dropping overflowed subscriber | conversation=%s",
                            conversation_id,
                        )
                        break

                    if await request.is_disconnected():
                        break

                    if event is None:
                        yield ": keepalive\n\n"
                        continue

                    yield format_sse(event)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    # ---- settings ------------------------------------------------------

    @app.get("/settings")
    async def get_settings(user: Annotated[User, Depends(current_user)]):
        return application.describe_settings()

    @app.patch("/settings", dependencies=[Depends(require_admin)])
    async def update_settings(changes: dict[str, Any]):
        try:
            await application.apply_settings(changes)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            # Validation already passed, so this is a storage failure, not a
            # bad request — 500, not 422.
            logger.exception("Failed to apply settings | changes=%s", changes)

            raise HTTPException(
                status_code=500,
                detail="Failed to apply settings.",
            ) from error

        return application.describe_settings()

    @app.delete("/settings/{key}", dependencies=[Depends(require_admin)])
    async def delete_setting(key: str):
        try:
            await application.reset_setting(key)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        return application.describe_settings()

    return app


def _existing_turn_response(
    existing: TurnLookup,
    conversation_id: UUID,
) -> JSONResponse:
    if existing.conversation_id != conversation_id:
        raise HTTPException(
            status_code=409,
            detail="client_message_id already used in another conversation",
        )

    return JSONResponse(
        status_code=200,
        content={
            "user_message_id": existing.user_message_id,
            "assistant_message_id": existing.assistant_message_id,
        },
    )


def _attachment_header(filename: str) -> str:
    """
    Content-Disposition for a download (RFC 6266).

    Both forms on purpose: `filename=` for the plain ASCII case, and
    `filename*=` carrying the UTF-8 original. Today's names are ASCII, but
    職務経歴書 filenames will not be, and non-ASCII bytes in a bare
    `filename=` are silently mangled rather than rejected.
    """
    ascii_fallback = (
        filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    )

    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
