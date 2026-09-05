import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import CONSOLE_LOG, CONVERSATION_LOG, LOG_LEVEL
from app.utils.conversation_log import (
    HANDLER_NAME,
    ExcludeConversationContent,
    setup_conversation_log,
)


def setup_logger():

    logger = logging.getLogger("llm_app")

    # Prevent duplicate handlers if logger is imported multiple times
    if logger.handlers:
        return logger

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    # The logger admits DEBUG only so the conversation-log handler can see
    # the records it exists for. Every other handler carries LOG_LEVEL as
    # its own level, so this changes nothing about what reaches the daily
    # log or the console.
    logger.setLevel(logging.DEBUG if CONVERSATION_LOG else level)

    log_dir = Path("app/logs")
    log_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{date_str}.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    # Attached whether or not the conversation log is on: the records it
    # rejects are only ever created when that log is on, so this costs
    # nothing when it is off and cannot be forgotten when it is turned on.
    file_handler.addFilter(ExcludeConversationContent())
    logger.addHandler(file_handler)

    if str(CONSOLE_LOG).lower() == "true":
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        console_handler.addFilter(ExcludeConversationContent())
        console_handler.stream.reconfigure(encoding="utf-8")
        logger.addHandler(console_handler)

    setup_conversation_log(logger)

    return logger


def set_log_level(level: str):
    """
    Change the level of the ordinary handlers.

    Applied per handler rather than to the logger, because the logger has
    to stay at DEBUG while the conversation log is on — lifting it would
    cut that handler off from the records it exists to capture, and a
    runtime `/set log_level INFO` would silently switch the file off.
    """
    resolved = getattr(logging, level.upper(), logging.INFO)

    logger.setLevel(logging.DEBUG if CONVERSATION_LOG else resolved)

    for handler in logger.handlers:
        if handler.name != HANDLER_NAME:
            handler.setLevel(resolved)


logger = setup_logger()
