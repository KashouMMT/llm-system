"""The /time slash command: current date and time in Japan (JST).

Unlike get_current_time (tools.py), this never reaches the LLM —
ChatService routes it directly and writes the return value as the
assistant message, verbatim, as Markdown.
"""

import time

from app.plugins.clock.tools import now_jst_text
from app.plugins.contracts import CommandContext
from app.utils.logger import logger


async def handle_time(context: CommandContext) -> str:
    start = time.perf_counter()

    logger.info(
        "Command started | command=/time conversation=%s",
        context.conversation_id,
    )

    result = f"Current time (JST): {now_jst_text()}"

    logger.info(
        "Command completed | command=/time elapsed=%.4fs",
        time.perf_counter() - start,
    )

    return result
