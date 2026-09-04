import time
from datetime import datetime

from langchain_core.tools import tool

from app.documents.dates import JST
from app.utils.logger import logger


@tool
def get_current_time() -> str:
    """Get the current date and time in Japan (JST).

    Use this tool when the user asks for the current time,
    current date, or wants to know what time/date it is.
    """
    start = time.perf_counter()

    logger.info("Tool started | tool=get_current_time")

    # JST rather than the host's local zone. Every document this assistant
    # produces is dated for a Japanese reader, and a server in another
    # region would otherwise report a date that is silently a day out.
    result = datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M:%S JST")

    elapsed = time.perf_counter() - start

    logger.info(
        "Tool completed | tool=get_current_time elapsed=%.4fs",
        elapsed,
    )
    
    return result