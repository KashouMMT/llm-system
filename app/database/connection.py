import psycopg
from psycopg_pool import AsyncConnectionPool

from app.config.settings import (
    DATABASE_URL,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_POOL_MAX_SIZE,
    DB_POOL_MIN_SIZE,
    DB_PORT,
    DB_USER,
)
from app.utils.logger import logger


def get_connection():
    """
    Open a single synchronous connection.

    Only for work that runs before the pool exists: creating the database,
    creating tables, and applying migrations. Everything else goes through
    the async pool, because a synchronous connection used from async code
    blocks the event loop — and therefore every open SSE stream at once.
    """
    try:
        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )

        logger.info("PostgreSQL connected")

        return conn

    except Exception as e:
        logger.exception("Failed to connect PostgreSQL")
        raise e  # noqa: TRY201


def create_pool() -> AsyncConnectionPool:
    """
    Build the shared async connection pool.

    Created unopened so it can be constructed before an event loop exists;
    Application.initialize() opens it and Application.shutdown() closes it.
    """
    return AsyncConnectionPool(
        conninfo=DATABASE_URL,
        min_size=DB_POOL_MIN_SIZE,
        max_size=DB_POOL_MAX_SIZE,
        open=False,
    )
