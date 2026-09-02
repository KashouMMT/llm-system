import json
from collections.abc import AsyncIterator
from dataclasses import fields
from typing import Any
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config.runtime_settings import (
    FIELD_PARSERS,
    PERSISTED_FIELDS,
    RuntimeSettings,
)
from app.config.settings import MAX_USER_INPUT_CHARS
from app.repositories.message_repository import TurnLookup
from app.runtime.application import Application
from app.runtime.event_bus import Event
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


def format_sse(event: Event) -> str:
    lines = []

    if event.id is not None:
        lines.append(f"id: {event.id}")

    lines.append(f"event: {event.type}")
    lines.append(f"data: {json.dumps(event.to_wire())}")

    return "\n".join(lines) + "\n\n"

def _settings_payload(current: RuntimeSettings) -> dict[str, dict[str, Any]]:
    """
    Every runtime-adjustable field: its live value, whether it survives a
    restart, and what the environment would fall back to.

    Mirrors print_settings() in app/runtime/cli.py, so the CLI and this
    endpoint describe the same state the same way.
    """
    defaults = RuntimeSettings.from_env()
    
    return {
        field.name: {
            "value": getattr(current, field.name),
            "persisted": field.name in PERSISTED_FIELDS,
            "default": getattr(defaults, field.name),
        }
        for field in fields(current)
    }



def create_api(application: Application) -> FastAPI:

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def require_conversation(conversation_id: UUID) -> None:
        exists = await application.conversation_repository.exists(
            conversation_id,
        )

        if not exists:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )

    @app.post("/conversations")
    async def create_conversation():

        conversation_id = (
            await application.conversation_repository.create_conversation()
        )

        return {
            "id": str(conversation_id),
        }

    @app.get("/conversations")
    async def get_conversations():

        conversations = await application.conversation_repository.get_conversations()

        return [
            {
                "id": str(conversation.id),
                "title": conversation.title,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
            }
            for conversation in conversations
        ]

    @app.get("/conversations/{conversation_id}/messages")
    async def get_messages(conversation_id: UUID):

        await require_conversation(conversation_id)

        messages = await application.message_repository.get_messages(
            conversation_id,
        )

        return [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
                "status": message.status,
            }
            for message in messages
        ]

    @app.post(
        "/conversations/{conversation_id}/messages",
        status_code=202,
    )
    async def send_message(
        conversation_id: UUID,
        request: SendMessageRequest,
    ):
        """
        Open a turn and start generating it in the background.

        Returns as soon as the rows exist. Tokens are delivered over
        GET /events, to every subscriber including this caller, so there is
        one token path rather than one per client role.
        """
        await require_conversation(conversation_id)

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
                user_input=request.message,
                client_message_id=request.client_message_id,
            )

        except psycopg.errors.UniqueViolation:
            # Lost a race on the idempotency key. The other caller's turn is
            # the real one; report it rather than generating a second answer.
            application.conversation_lock.release(conversation_id)

            existing = (
                await application.message_repository.get_turn_by_client_message_id(
                    request.client_message_id,
                )
            )

            if existing is None:
                raise

            return _existing_turn_response(existing, conversation_id)

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

    @app.get("/events")
    async def events(conversation_id: UUID, request: Request):
        """
        Server-sent events for one conversation.

        Any number of clients may subscribe; every one receives the same
        stream. This is what makes several tabs consistent — not a feature
        layered on top, but the absence of a per-client token path.
        """
        await require_conversation(conversation_id)

        async def generator() -> AsyncIterator[str]:
            async with application.event_bus.subscribe(
                conversation_id,
            ) as subscription:
                # Browsers honour this as the reconnect delay.
                yield "retry: 3000\n\n"

                while True:
                    event = await subscription.next_event(
                        # Read each pass, so a change reaches streams that
                        # are already open.
                        timeout=application.runtime_settings.current
                        .sse_heartbeat_seconds,
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
                        # Idle proxies drop connections without traffic, and
                        # this is also how the client notices a dead link.
                        yield ": keepalive\n\n"
                        continue

                    yield format_sse(event)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
        
    @app.get("/settings")
    async def get_settings():
        return _settings_payload(application.runtime_settings.current)
    
    # TODO: gate behind auth once the login system exists. An
    # unauthenticated PATCH here can rewrite system_prompt_name, which is
    # a persistent, silent change to what the assistant does for every
    # user — not bad data in a row, but a change in behavior. Left open
    # only because this is a solo local-network dev environment.
    @app.patch("/settings")
    async def update_settings(changes: dict[str, Any]):
        try:
            updated = await application.apply_settings(changes)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            # Validation already passed by this point, so this is a
            # storage failure (e.g. the DB connection dropped mid-write)
            # rather than a bad request — 500, not 422.
            logger.exception("Failed to apply settings | changes=%s", changes)

            raise HTTPException(
                status_code=500,
                detail="Failed to apply settings.",
            ) from error

        return _settings_payload(updated)

    # TODO: gate behind auth once the login system exists. Same reasoning
    # as PATCH /settings above.
    @app.delete("/settings/{key}")
    async def delete_setting(key: str):
        if key not in FIELD_PARSERS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown or non-editable setting: {key}",
            )
        
        default = getattr(RuntimeSettings.from_env(), key)
        
        try:
            updated = await application.apply_settings({key: default})
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        
        if key in PERSISTED_FIELDS:
            await application.settings_repository.delete(key)
        
        return _settings_payload(updated)
        

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
