import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.config.settings import SSE_QUEUE_MAXSIZE
from app.utils.logger import logger

EVENT_SCHEMA_VERSION = 1

EVENT_MESSAGE_CREATED = "message.created"
EVENT_MESSAGE_DELTA = "message.delta"
EVENT_MESSAGE_COMPLETED = "message.completed"
EVENT_MESSAGE_CANCELLED = "message.cancelled"
EVENT_MESSAGE_FAILED = "message.failed"
EVENT_CONVERSATION_UPDATED = "conversation.updated"

@dataclass(frozen=True)
class Event:
    """
    One realtime notification about a conversation.

    `id` is the messages.id this event concerns, and is emitted as the SSE
    id: field for durable events only. Deltas leave it unset: they are not
    replayable, and a reconnecting client recovers by refetching messages
    rather than by replaying tokens.
    """
    type: str
    conversation_id: UUID
    payload: dict[str, Any]
    id: int | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "v": EVENT_SCHEMA_VERSION,
            "type": self.type,
            "conversation_id": str(self.conversation_id),
            "payload": self.payload,
        }
        
class Subscription:
    """
    One subscriber's view of a conversation's event stream.

    Bounded on purpose. A backgrounded tab that stops reading must not grow
    a queue without limit, so an overflowing subscription is marked dead and
    the reader disconnects instead.
    """
    def __init__(
        self,
        conversation_id: UUID,
        maxsize: int,
    ) -> None:
        self.conversation_id = conversation_id
        self.overflowed = False
        
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        
    def offer(self, event: Event) -> bool:
        """
        Enqueue without blocking. False means this subscription is finished.
        """
        if self.overflowed:
            return False
        
        try:
            self._queue.put_nowait(event)
            
            return True

        except asyncio.QueueFull:
            self.overflowed = True
            
            return False
        
    async def next_event(self, timeout: float) -> Event | None:
        """
        Wait for the next event, or return None when `timeout` elapses.

        None is the caller's cue to emit a heartbeat.
        """
        try:
            return await asyncio.wait_for(
                self._queue.get(),
                timeout=timeout,
            )

        except TimeoutError:
            return None
        
class EventBus:
    """
    In-process fan-out of conversation events.

    publish() is synchronous and never blocks, so a slow subscriber cannot
    stall a generation. Replacing this with Postgres LISTEN/NOTIFY for
    multi-worker deployment should not require changes outside this module.
    """
    def __init__(
        self,
        queue_maxsize = SSE_QUEUE_MAXSIZE,
    ) -> None:
        self.queue_maxsize = queue_maxsize
        self._subscribers: dict[UUID, set[Subscription]] = {}
        
    @asynccontextmanager
    async def subscribe(
        self,
        conversation_id: UUID,
    ) -> AsyncGenerator[Subscription, None]:
        
        subscription = Subscription(
            conversation_id=conversation_id,
            maxsize=self.queue_maxsize,
        )
        
        self._subscribers.setdefault(conversation_id, set()).add(subscription)
        
        logger.debug(
            "Subscriber attached | conversation=%s subscribers=%s",
            conversation_id,
            len(self._subscribers[conversation_id]),
        )
        
        try:
            yield subscription
            
        finally:
            subscribers = self._subscribers.get(conversation_id)
            
            if subscribers is not None:
                subscribers.discard(subscription)
                
                if not subscribers:
                    del self._subscribers[conversation_id]
                    
            logger.debug(
                "Subscriber detached | conversation=%s",
                conversation_id,
            )
            
    def publish(self, event: Event) -> None:
        subscribers = self._subscribers.get(event.conversation_id)
        
        if not subscribers:
            return
        
        # Snapshot: offer() can mark a subscription dead, and the reader
        # removes itself from this set on its own schedule.
        for subscription in list(subscribers):
            if not subscription.offer(event):
                logger.warning(
                    "Subscriber overflowed and will be dropped | "
                    "conversation=%s",
                    event.conversation_id,
                )
                
    def subscriber_count(self, conversation_id: UUID) -> int:
        return len(self._subscribers.get(conversation_id, ()))