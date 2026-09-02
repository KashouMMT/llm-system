from datetime import datetime
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.authentication.models import User


class SessionRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(
        self,
        user_id: UUID,
        token_hash: bytes,
        expires_at: datetime,
    ) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                INSERT INTO sessions (token_hash, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token_hash, user_id, expires_at),
            )

    async def get_user_by_token(self, token_hash: bytes) -> User | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                """
                SELECT
                    u.id,
                    u.username,
                    u.password_hash,
                    u.role,
                    u.created_at,
                    u.updated_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s
                  AND s.expires_at > NOW()
                """,
                (token_hash,),
            )

            return await cur.fetchone()

    async def delete(self, token_hash: bytes) -> None:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "DELETE FROM sessions WHERE token_hash = %s",
                (token_hash,),
            )

    async def delete_for_user(self, user_id: UUID) -> None:
        """Log a user out of every session (e.g. after a role change)."""
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "DELETE FROM sessions WHERE user_id = %s",
                (user_id,),
            )
