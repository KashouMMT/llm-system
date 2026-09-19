"""
Account management for the root user: list, create, edit and delete.

The rules live here rather than in the route handlers, so they hold for
any future caller (a CLI command, say):

- Only 'user' and 'admin' can be assigned. There is exactly one root,
  seeded from AUTH_BOOTSTRAP_* and reset with --seed-admin; the database
  enforces "at most one" (uq_users_single_root).
- The root account itself is not managed here at all — not edited, not
  deleted. Its recovery path is the environment, and a root that could
  demote or delete itself through the UI could lock everyone out.
- A password change signs that user out everywhere: whoever held the old
  password should not keep a session.
- Delete is a hard delete: the database cascade takes every row the
  account owns, and this service then removes what the cascade cannot
  reach — LangGraph checkpoint threads and file bytes. A
  "ban" (keep the data, refuse the login) is the better long-term
  semantics and is noted as the follow-up; delete is what exists today.

A role change needs no session handling: the session lookup re-reads the
user row on every request, so a demotion applies on the next request.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from psycopg.errors import UniqueViolation

from app.authentication.authorization import ROLE_ADMIN, ROLE_ROOT, ROLE_USER
from app.authentication.models import User
from app.authentication.passwords import hash_password
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.storage.base import FileStorage
from app.utils.logger import logger

ASSIGNABLE_ROLES = (ROLE_USER, ROLE_ADMIN)


class UserAdminError(Exception):
    """A refused account change; the message is safe to show the root user."""


class UserNotFoundError(UserAdminError):
    pass


class EmailTakenError(UserAdminError):
    pass


class RootProtectedError(UserAdminError):
    pass


class UserAdminService:
    def __init__(
        self,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        file_storage: FileStorage,
        delete_thread: Callable[[str], Awaitable[None]],
    ) -> None:
        self._users = user_repository
        self._sessions = session_repository
        self._storage = file_storage
        # The checkpointer's adelete_thread, passed as a plain callable so
        # account management never imports LangGraph. Checkpoint threads are
        # keyed by the conversation id as text, with no foreign key, so the
        # database cascade cannot reach them.
        self._delete_thread = delete_thread

    async def list_users(self) -> list[User]:
        return await self._users.list_all()

    async def create_user(
        self,
        *,
        actor: User,
        email: str,
        password: str,
        role: str,
    ) -> User:
        _check_role(role)
        normalised = email.strip().lower()

        # argon2 is CPU-bound; off the event loop, as in AuthService.
        password_hash = await asyncio.to_thread(hash_password, password)

        try:
            user = await self._users.create(normalised, password_hash, role)
        except UniqueViolation as error:
            raise EmailTakenError("That email is already registered.") from error

        logger.info(
            "User created by root | actor=%s id=%s email=%s role=%s",
            actor.email,
            user.id,
            user.email,
            user.role,
        )

        return user

    async def update_user(
        self,
        *,
        actor: User,
        user_id: UUID,
        email: str | None = None,
        password: str | None = None,
        role: str | None = None,
    ) -> User:
        await self._editable(user_id)

        if role is not None:
            _check_role(role)

        password_hash = (
            None
            if password is None
            else await asyncio.to_thread(hash_password, password)
        )

        try:
            user = await self._users.update(
                user_id,
                email=None if email is None else email.strip().lower(),
                password_hash=password_hash,
                role=role,
            )
        except UniqueViolation as error:
            raise EmailTakenError("That email is already registered.") from error

        if user is None:
            # Deleted between the check above and the update.
            raise UserNotFoundError("No such user.")

        if password_hash is not None:
            await self._sessions.delete_for_user(user_id)

        logger.info(
            "User updated by root | actor=%s id=%s email_changed=%s "
            "password_changed=%s role=%s",
            actor.email,
            user_id,
            email is not None,
            password_hash is not None,
            role,
        )

        return user

    async def delete_user(self, *, actor: User, user_id: UUID) -> None:
        await self._editable(user_id)

        deleted = await self._users.delete(user_id)

        if deleted is None:
            raise UserNotFoundError("No such user.")

        # After the rows are gone (see UserRepository.delete). Best effort:
        # a leftover checkpoint thread or blob belongs to a conversation
        # that no longer exists, is never read again, and is harmless — one
        # failed cleanup must not fail the request that removed the account.
        for conversation_id in deleted.conversation_ids:
            try:
                await self._delete_thread(str(conversation_id))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Deleted user's checkpoint thread not removed | thread=%s",
                    conversation_id,
                )

        for key in deleted.storage_keys:
            try:
                await self._storage.delete(key)
            except Exception:  # noqa: BLE001
                logger.exception("Deleted user's file bytes not removed | key=%s", key)

        logger.info(
            "User deleted by root | actor=%s id=%s conversations=%s files=%s",
            actor.email,
            user_id,
            len(deleted.conversation_ids),
            len(deleted.storage_keys),
        )

    async def _editable(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)

        if user is None:
            raise UserNotFoundError("No such user.")

        if user.role == ROLE_ROOT:
            raise RootProtectedError(
                "The root account is managed from the server environment "
                "(AUTH_BOOTSTRAP_EMAIL / AUTH_BOOTSTRAP_PASSWORD, --seed-admin), "
                "not here."
            )

        return user


def _check_role(role: str) -> None:
    # The API's request model already restricts this; checked again so the
    # rule does not depend on which caller is asking.
    if role not in ASSIGNABLE_ROLES:
        raise UserAdminError(f"Role must be one of: {', '.join(ASSIGNABLE_ROLES)}.")
