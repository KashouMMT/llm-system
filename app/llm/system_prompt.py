from pathlib import Path

from app.config.settings import DEFAULT_PROMPT, SYSTEM_PROMPT
from app.utils.logger import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

def load_system_prompt(name: str = SYSTEM_PROMPT) -> str:
    """
    Load a system prompt by name from app/prompts/<name>.txt.

    Falls back to DEFAULT_PROMPT if the file is missing or empty, so a
    bad SYSTEM_PROMPT value degrades to a usable assistant rather than
    failing startup.
    """
    prompt_path = PROMPTS_DIR / f"{name}.txt"
    
    if not prompt_path.is_file():
        logger.warning(
            "System prompt not found, using default | name=%s path=%s",
            name,
            prompt_path,
        )
        return DEFAULT_PROMPT

    content = prompt_path.read_text(encoding="utf-8").strip()
    
    if not content:
        logger.warning(
            "System prompt file is empty, using default | name=%s",
            name,
        )
        return DEFAULT_PROMPT
    
    logger.debug(
        "System prompt loaded | name=%s characters=%s", name, len(content)
    )
    
    return content