from pathlib import Path
from app.config.settings import SYSTEM_PROMPT, DEFAULT_PROMPT
from app.utils.logger import logger

def load_prompt() -> str:
    base_path = Path(__file__).resolve().parent.parent
    prompts_dir = base_path / "prompts"
    
    prompt_path = prompts_dir / f"{SYSTEM_PROMPT}.txt"
    
    if not prompt_path.exists():
        logger.warning(f"Prompt '{SYSTEM_PROMPT}' not found. Using default prompt.")
        return DEFAULT_PROMPT
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()