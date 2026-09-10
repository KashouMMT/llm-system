from uuid import UUID, uuid4

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from app.authentication.models import User
from app.utils.logger import logger

_USER_COLUMNS = """
    id,
    email,
    password_hash,
    role,
    created_at,
    updated_at
"""


class UserRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_by_email(self, email: str) -> User | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"SELECT {_USER_COLUMNS} FROM users WHERE email = %s",
                (email,),
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
        email: str,
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
                INSERT INTO users (id, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
                RETURNING {_USER_COLUMNS}
                """,
                (user_id, email, password_hash, role),
            )

            created = await cur.fetchone()

        logger.info(
            "User created | id=%s email=%s role=%s",
            created.id,
            created.email,
            created.role,
        )

        return created

    async def update_root_credentials(
        self,
        user_id: UUID,
        email: str,
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
                SET email = %s,
                    password_hash = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (email, password_hash, user_id),
            )

        logger.info("Root credentials reset | id=%s email=%s", user_id, email)
