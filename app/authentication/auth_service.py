import asyncio
from datetime import datetime, timedelta, timezone

from app.authentication.models import User
from app.authentication.passwords import verify_dummy, verify_password
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
        username: str,
        password: str,
    ) -> tuple[User, str, datetime] | None:
        """
        Return (user, raw_token, expires_at) on success, None on bad
        credentials.

        argon2 verification is CPU-bound (~tens of ms, 64 MiB) and would
        otherwise stall the single event loop that also serves the SSE
        streams, so it runs in a worker thread. The unknown-username branch
        still burns one verification so response time does not distinguish
        "no such user" from "wrong password".
        """
        user = await self._users.get_by_username(username.strip().lower())

        if user is None:
            await asyncio.to_thread(verify_dummy, password)
            logger.info("Login failed: unknown username")
            return None

        ok = await asyncio.to_thread(
            verify_password,
            user.password_hash,
            password,
        )

        if not ok:
            logger.info("Login failed: bad password | username=%s", user.username)
            return None

        token = generate_session_token()
        expires_at = datetime.now(timezone.utc) + self._ttl

        await self._sessions.create(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )

        logger.info(
            "Login succeeded | username=%s role=%s",
            user.username,
            user.role,
        )

        return user, token, expires_at

    async def resolve(self, token: str | None) -> User | None:
        if not token:
            return None

        return await self._sessions.get_user_by_token(hash_session_token(token))

    async def logout(self, token: str | None) -> None:
        if token:
            await self._sessions.delete(hash_session_token(token))