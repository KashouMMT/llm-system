import logging
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

from app.config.settings import LOG_LEVEL, CONSOLE_LOG

def setup_logger():
    
    logger = logging.getLogger("llm_app")
    
    # Prevent duplicate handlers if logger is imported multiple times
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    
    log_dir = Path("app/logs")
    log_dir.mkdir(exist_ok=True)
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{date_str}.log"
    
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s | %(message)s"
    )
    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024, # 5MB
        backupCount=5
    )
    
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    if str(CONSOLE_LOG).lower() == "true":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()