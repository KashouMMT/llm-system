import time
from datetime import datetime

from langchain_core.tools import tool

from app.utils.jst import JST
from app.utils.logger import logger


def now_jst_text() -> str:
    """Current date and time in Japan (JST), formatted for a person to read.

    JST rather than the host's local zone. Every document this assistant
    produces is dated for a Japanese reader, and a server in another
    region would otherwise report a date that is silently a day out.

    Shared by the get_current_time tool and the /time command, so the
    model-facing path and the deterministic slash-command path never
    drift into reporting the time in two different formats.
    """
    return datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M:%S JST")


@tool
def get_current_time() -> str:
    """Get the current date and time in Japan (JST).

    Use this tool when the user asks for the current time,
    current date, or wants to know what time/date it is.
    """
    start = time.perf_counter()

    logger.info("Tool started | tool=get_current_time")

    result = now_jst_text()

    elapsed = time.perf_counter() - start

    logger.info(
        "Tool completed | tool=get_current_time elapsed=%.4fs",
        elapsed,
    )

    return result