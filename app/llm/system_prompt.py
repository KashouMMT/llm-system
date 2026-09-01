from pathlib import Path

from app.config.settings import DEFAULT_PROMPT, SYSTEM_PROMPT
from app.utils.logger import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Appended to every persona, including the fallback.
#
# This describes the rendering surface, not a personality: the frontend
# passes assistant output through a Markdown renderer, and no model can
# infer that on its own. Persona files stay free to describe only who
# the assistant is and what it helps with.
#
# Deliberately short — the system prompt rides on every request, so
# anything here is paid for on each turn. State what the renderer
# supports and what it does not; do not teach Markdown itself.
RESPONSE_FORMAT = """
==================================================
RESPONSE FORMAT
==================================================

Your replies are displayed through a Markdown renderer, so Markdown
syntax is rendered rather than shown literally. Use it to make answers
easier to read:

- **bold** for emphasis, headings for sections, and bullet or numbered
  lists for anything enumerable.
- Tables for comparisons.
- Fenced code blocks with a language tag (```python) for code, and for
  any text whose exact spacing and punctuation must be preserved.
- ```mermaid fences are supported and rendered as diagrams. Use one
  when a flow, timeline, or relationship is clearer drawn than
  described.

LaTeX and raw HTML are NOT rendered — do not emit them.

Match formatting to the answer. A one-line reply needs no headings; a
conversational answer does not need to become a bulleted list.
""".strip()


# Roughly 20% of a 16k context window. The system prompt is re-sent on
# every request, so growth here is paid for on each turn — and a small
# model follows a long prompt less reliably than a short one. Crossing
# this is a prompt to delete something, not a failure.
SYSTEM_PROMPT_TOKEN_BUDGET = 3000


def _estimate_tokens(text: str) -> int:
    """
    Rough token count, using the same 4-chars-per-token heuristic as
    SummarizationService so the two do not drift apart.

    Undercounts Japanese, which tokenizes closer to one token per
    character. Adequate for a budget warning; not a billing figure.
    """
    return len(text) // 4


def _compose(persona: str) -> str:
    """Attach the renderer contract to a persona."""
    prompt = f"{persona}\n\n{RESPONSE_FORMAT}"

    estimated_tokens = _estimate_tokens(prompt)

    if estimated_tokens > SYSTEM_PROMPT_TOKEN_BUDGET:
        # Warn rather than raise: a long prompt is still a working
        # prompt, and this module's contract is that a bad SYSTEM_PROMPT
        # degrades instead of preventing startup.
        logger.warning(
            "System prompt exceeds token budget | estimated_tokens=%s "
            "budget=%s characters=%s",
            estimated_tokens,
            SYSTEM_PROMPT_TOKEN_BUDGET,
            len(prompt),
        )

    return prompt


def load_system_prompt(name: str = SYSTEM_PROMPT) -> str:
    """
    Load a system prompt by name from app/prompts/<name>.txt.

    Falls back to DEFAULT_PROMPT if the file is missing or empty, so a
    bad SYSTEM_PROMPT value degrades to a usable assistant rather than
    failing startup.

    Every path returns the persona with RESPONSE_FORMAT appended — the
    formatting contract belongs to the interface, so it must not depend
    on which persona happened to load, or on whether one loaded at all.
    """
    prompt_path = PROMPTS_DIR / f"{name}.txt"

    if not prompt_path.is_file():
        logger.warning(
            "System prompt not found, using default | name=%s path=%s",
            name,
            prompt_path,
        )
        return _compose(DEFAULT_PROMPT)

    content = prompt_path.read_text(encoding="utf-8").strip()

    if not content:
        logger.warning(
            "System prompt file is empty, using default | name=%s",
            name,
        )
        return _compose(DEFAULT_PROMPT)

    logger.debug(
        "System prompt loaded | name=%s characters=%s", name, len(content)
    )

    return _compose(content)
