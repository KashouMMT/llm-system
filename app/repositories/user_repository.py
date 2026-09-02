from uuid import UUID, uuid4

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.authentication.models import User
from app.utils.logger import logger

_USER_COLUMNS = """
    id,
    username,
    password_hash,
    role,
    created_at,
    updated_at
"""


class UserRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_by_username(self, username: str) -> User | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE username = %s",
                (username,),
            )

            return await cur.fetchone()

    async def get_by_id(self, user_id: UUID) -> User | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s",
                (user_id,),
            )

            return await cur.fetchone()

    async def get_root(self) -> User | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE role = 'root'",
            )

            return await cur.fetchone()

    async def create(
        self,
        username: str,
        password_hash: str,
        role: str,
    ) -> User:
        user_id = uuid4()

        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"""
                INSERT INTO users (id, username, password_hash, role)
                VALUES (%s, %s, %s, %s)
                RETURNING {_USER_COLUMNS}
                """,
                (user_id, username, password_hash, role),
            )

            created = await cur.fetchone()

        logger.info(
            "User created | id=%s username=%s role=%s",
            created.id,
            created.username,
            created.role,
        )

        return created

    async def update_root_credentials(
        self,
        user_id: UUID,
        username: str,
        password_hash: str,
    ) -> None:
        """Reset the root user from the environment (the recovery path)."""
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                """
                UPDATE users
                SET username = %s,
                    password_hash = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (username, password_hash, user_id),
            )

        logger.info("Root credentials reset | id=%s username=%s", user_id, username)
