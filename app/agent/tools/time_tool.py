import time
from datetime import datetime

from langchain_core.tools import tool

from app.utils.logger import logger


@tool
def get_current_time() -> str:
    """Get the current local date and time.

    Use this tool when the user asks for the current time,
    current date, or wants to know what time/date it is.
    """
    start = time.perf_counter()

    logger.info("Tool started | tool=get_current_time")

    result = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    elapsed = time.perf_counter() - start

    logger.info(
        "Tool completed | tool=get_current_time elapsed=%.4fs",
        elapsed,
    )
    
    return result