"""The /clock command namespace: today, just /clock time.

Unlike get_current_time (tools.py), this never reaches the LLM —
ChatService routes it directly and writes the return value as the
assistant message, verbatim, as Markdown. One namespace per plugin, one
handler that dispatches on context.subcommand — the same shape every
future plugin's own commands.py follows.
"""

import time

from app.plugins.clock.tools import now_jst_text
from app.plugins.contracts import CommandContext
from app.utils.logger import logger

_HELP = "Available: `time`"


async def _time(context: CommandContext) -> str:
    return f"Current time (JST): {now_jst_text()}"


_SUBCOMMANDS = {
    "time": _time,
}


async def handle_clock(context: CommandContext) -> str:
    start = time.perf_counter()

    handler = _SUBCOMMANDS.get(context.subcommand)

    logger.info(
        "Command started | command=/clock %s conversation=%s",
        context.subcommand,
        context.conversation_id,
    )

    if handler is None:
        result = f"Unknown `/clock` subcommand: `{context.subcommand}`.\n\n{_HELP}"
    else:
        result = await handler(context)

    logger.info(
        "Command completed | command=/clock %s elapsed=%.4fs",
        context.subcommand,
        time.perf_counter() - start,
    )

    return result
