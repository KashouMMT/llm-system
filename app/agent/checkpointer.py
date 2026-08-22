from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config.settings import DATABASE_URL
from app.utils.logger import logger


def create_checkpointer():
    """
    Create the LangGraph PostgreSQL checkpointer context.

    The returned context manager owns the asynchronous PostgreSQL
    resources required by AsyncPostgresSaver.

    Application is responsible for entering and exiting this
    context during its own lifecycle.
    """

    logger.info("Creating LangGraph PostgreSQL checkpointer context")

    checkpointer_context = AsyncPostgresSaver.from_conn_string(DATABASE_URL)

    logger.debug("LangGraph PostgreSQL checkpointer context created")

    return checkpointer_context
