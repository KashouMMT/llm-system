import asyncio
from datetime import datetime, timedelta, timezone

from psycopg.errors import UniqueViolation

from app.authentication.authorization import ROLE_USER
from app.authentication.models import User
from app.authentication.passwords import hash_password, verify_dummy, verify_password
from app.authentication.tokens import (
    generate_session_token,
    hash_session_token,
)
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.utils.logger import logger


class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        session_ttl_hours: int,
    ) -> None:
        self._users = user_repository
        self._sessions = session_repository
        self._ttl = timedelta(hours=session_ttl_hours)

    async def login(
        self,
        email: str,
        password: str,
    ) -> tuple[User, str, datetime] | None:
        """
        Return (user, raw_token, expires_at) on success, None on bad
        credentials.

        argon2 verification is CPU-bound (~tens of ms, 64 MiB) and would
        otherwise stall the single event loop that also serves the SSE
        streams, so it runs in a worker thread. The unknown-email branch
        still burns one verification so response time does not distinguish
        "no such user" from "wrong password".
        """
        user = await self._users.get_by_email(email.strip().lower())

        if user is None:
            await asyncio.to_thread(verify_dummy, password)
            logger.info("Login failed: unknown email")
            return None

        ok = await asyncio.to_thread(
            verify_password,
            user.password_hash,
            password,
        )

        if not ok:
            logger.info("Login failed: bad password | email=%s", user.email)
            return None

        token = generate_session_token()
        expires_at = datetime.now(timezone.utc) + self._ttl

        await self._sessions.create(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )

        logger.info(
            "Login succeeded | email=%s role=%s",
            user.email,
            user.role,
        )

        return user, token, expires_at

    async def register(self, email: str, password: str) -> User | None:
        """
        Create a normal-role ('user') account.

        Return the new User, or None if the email is already registered.

        The email is normalised the same way login normalises it
        (strip().lower()), so the address entered on the sign-up form is
        the same address entered on the login form. Like login, the argon2
        hash is CPU-bound and runs in a worker thread so it does not stall
        the event loop that also serves the SSE streams.
        """
        normalised = email.strip().lower()

        if await self._users.get_by_email(normalised) is not None:
            logger.info(
                "Registration rejected: email taken | email=%s",
                normalised,
            )
            return None

        password_hash = await asyncio.to_thread(hash_password, password)

        try:
            user = await self._users.create(normalised, password_hash, ROLE_USER)
        except UniqueViolation:
            # The email was registered between the check above and this
            # insert; the database UNIQUE constraint is the real guard.
            logger.info(
                "Registration rejected: email taken (race) | email=%s",
                normalised,
            )
            return None

        logger.info("Registration succeeded | email=%s", user.email)
        return user

    async def resolve(self, token: str | None) -> User | None:
        if not token:
            return None

        return await self._sessions.get_user_by_token(hash_session_token(token))

    async def logout(self, token: str | None) -> None:
        if token:
            await self._sessions.delete(hash_session_token(token))