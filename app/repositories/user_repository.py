from dataclasses import dataclass
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


@dataclass(frozen=True)
class DeletedUser:
    """What a user's deletion left for the caller: the database cascade
    covers every row, but not bytes on disk or checkpoint threads."""

    storage_keys: list[str]
    conversation_ids: list[UUID]


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

    # ---- user management (root) ------------------------------------------

    async def list_all(self) -> list[User]:
        """Every account, root first, then oldest first."""
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"SELECT {_USER_COLUMNS} FROM users "
                "ORDER BY (role = 'root') DESC, created_at, email",
            )

            return await cur.fetchall()

    async def update(
        self,
        user_id: UUID,
        *,
        email: str | None = None,
        password_hash: str | None = None,
        role: str | None = None,
    ) -> User | None:
        """Change only the fields given. None when no such user. A taken
        email raises psycopg's UniqueViolation, for the caller to map."""
        changes = {
            column: value
            for column, value in (
                ("email", email),
                ("password_hash", password_hash),
                ("role", role),
            )
            if value is not None
        }

        if not changes:
            return await self.get_by_id(user_id)

        # Column names come from the fixed tuple above, never from input.
        assignments = ", ".join(f"{column} = %s" for column in changes)

        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(User)) as cur,
        ):
            await cur.execute(
                f"""
                UPDATE users SET {assignments}, updated_at = NOW()
                WHERE id = %s
                RETURNING {_USER_COLUMNS}
                """,
                (*changes.values(), user_id),
            )

            return await cur.fetchone()

    async def delete(self, user_id: UUID) -> DeletedUser | None:
        """
        Delete one account and, by ON DELETE CASCADE, everything it owns:
        sessions, conversations, messages, summaries, file rows (and the
        recycling evidence rows pointing at those files).

        Returns what the cascade cannot reach, for the caller to clean up
        after this commits: the files' storage keys (bytes on disk) and the
        conversation ids (LangGraph checkpoint threads, which have no
        foreign key). Rows first, then the rest — the same order as
        FileRepository.sweep_orphaned_uploads: a failure then leaves
        something unreferenced, never a row pointing at what is gone. None
        when no such user.

        One transaction, so what is read is exactly what is deleted.
        """
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT id FROM conversations WHERE user_id = %s", (user_id,)
            )
            conversation_ids = [row[0] for row in await cur.fetchall()]

            cur = await conn.execute(
                """
                SELECT storage_key FROM files
                WHERE user_id = %s
                   OR conversation_id IN (
                       SELECT id FROM conversations WHERE user_id = %s
                   )
                """,
                (user_id, user_id),
            )
            storage_keys = [row[0] for row in await cur.fetchall()]

            cur = await conn.execute("DELETE FROM users WHERE id = %s", (user_id,))

            if cur.rowcount == 0:
                return None

        logger.info(
            "User deleted | id=%s conversations=%s files=%s",
            user_id,
            len(conversation_ids),
            len(storage_keys),
        )

        return DeletedUser(
            storage_keys=storage_keys,
            conversation_ids=conversation_ids,
        )

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
