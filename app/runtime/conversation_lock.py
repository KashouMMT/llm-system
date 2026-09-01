from uuid import UUID

from app.utils.logger import logger


class ConversationLock:
    """
    Serializes generation per conversation.

    The agent graph is checkpointed under thread_id = conversation_id, so two
    concurrent runs on one conversation would branch from and overwrite the
    same checkpoint. One user with two tabs is enough to cause that.

    Correct without a mutex only because acquire never awaits between the
    membership test and the insert. Keep it that way.

    In-process only: a second worker would not see these. Postgres advisory
    locks are the cross-worker replacement, and they share this property of
    releasing automatically when the holder dies.
    """

    def __init__(self) -> None:
        self._in_flight: dict[UUID, int | None] = {}

    def try_acquire(self, conversation_id: UUID) -> bool:
        if conversation_id in self._in_flight:
            return False

        self._in_flight[conversation_id] = None

        return True

    def attach_message_id(
        self,
        conversation_id: UUID,
        assistant_message_id: int,
    ) -> None:
        """
        Record which assistant message the in-flight turn is producing, so a
        rejected caller can be told which stream to join instead of erroring.
        """
        if conversation_id not in self._in_flight:
            logger.warning(
                "Attaching message id to an unlocked conversation | conversation=%s",
                conversation_id,
            )

        self._in_flight[conversation_id] = assistant_message_id

    def release(self, conversation_id: UUID) -> None:
        self._in_flight.pop(conversation_id, None)

    def is_locked(self, conversation_id: UUID) -> bool:
        return conversation_id in self._in_flight

    def in_flight_message_id(self, conversation_id: UUID) -> int | None:
        """
        None means either not locked, or locked but the row is not inserted
        yet. Callers should test is_locked() first; a rejected client that
        gets None simply refetches messages.
        """
        return self._in_flight.get(conversation_id)
