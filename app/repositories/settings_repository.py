from psycopg_pool import AsyncConnectionPool


class SettingsRepository:
    """
    Persisted overrides for runtime-adjustable settings.

    Values are stored as text and parsed by RuntimeSettingsHolder, so the
    database and the API go through exactly one validation path.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_all(self) -> dict[str, str]:
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute("SELECT key, value FROM app_settings")

            return {key: value for key, value in await cur.fetchall()}

    async def upsert_many(self, values: dict[str, str]) -> None:
        if not values:
            return

        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.executemany(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    updated_at = NOW()
                """,
                list(values.items()),
            )

    async def delete(self, key: str) -> None:
        """Drop an override so the setting falls back to the environment."""
        async with (
            self._pool.connection() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "DELETE FROM app_settings WHERE key = %s",
                (key,),
            )