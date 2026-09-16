from app.config.prompts import (
    FIRST_MESSAGE_FILE,
    SUMMARY_CHUNK_PROMPT_FILE,
    SUMMARY_MERGE_PROMPT_FILE,
    SYSTEM_PROMPT_FILE,
    TITLE_PROMPT_FILE,
    read_optional_prompt_file,
    read_prompt_file,
    resolve_prompt_set,
)
from app.config.settings import (
    DEFAULT_PROMPT,
    DEFAULT_TITLE_PROMPT,
    SUMMARY_CHUNK_PROMPT,
    SUMMARY_MERGE_PROMPT,
    SYSTEM_PROMPT,
)
from app.utils.logger import logger

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
#
# Nothing about a *plugin* belongs here, however true it is of the
# current deployment. This block is appended whatever is loaded, so an
# instruction here to call a tool becomes a lie the moment that plugin
# enters EXCLUDED_TOOL_PLUGINS. Plugin-specific standing instructions go
# in that plugin's own plugin_prompt.txt, which is injected only while
# the plugin is loaded — see ToolPlugin.system_prompt.
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


# Header for the block of plugin-contributed prompts, written once here
# rather than by each plugin, so several loaded plugins produce one
# labelled section instead of N competing banners.
#
# It says "tools" rather than "plugins": which folders the operator
# enabled is an implementation fact the model has no use for, and naming
# it invites the model to talk about plugins to the user.
TOOL_NOTES_HEADER = """
==================================================
YOUR TOOLS
==================================================
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


def _compose(persona: str, plugin_prompts: str = "") -> str:
    """
    Attach the renderer contract, then whatever the loaded plugins had to
    say, to a persona.

    Plugin text goes last on purpose. The persona is who the assistant is
    and the renderer contract is how it writes; a plugin's standing
    instructions are about the tools in front of it, which is the most
    situational of the three and the part most likely to be absent
    entirely.
    """
    prompt = f"{persona}\n\n{RESPONSE_FORMAT}"

    if plugin_prompts.strip():
        prompt = f"{prompt}\n\n{TOOL_NOTES_HEADER}\n\n{plugin_prompts.strip()}"

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


def load_system_prompt(
    name: str = SYSTEM_PROMPT,
    plugin_prompts: str = "",
) -> str:
    """
    Load the persona for prompt set `name` from
    app/prompts/<name>/system_prompt.txt.

    `plugin_prompts` is the block returned by
    app.plugins.loader.load_plugin_prompts, collected once at startup and
    handed down through AgentGraph to the agent node, which is the only
    caller that needs it. It is a parameter rather than a module global
    because which plugins are loaded is a property of one Application
    instance — a second Application in the same process (tests do this)
    must be able to load a different set.

    Set resolution is all-or-nothing (see app.config.prompts): if that
    folder is missing any of its three files, the whole set — persona
    included — falls back to app/prompts/default/. If even that cannot be
    read, this degrades to the built-in DEFAULT_PROMPT rather than
    failing, so a bad SYSTEM_PROMPT value never takes the assistant down.

    Every path returns the persona with RESPONSE_FORMAT and the plugin
    block appended — the formatting contract belongs to the interface, so
    it must not depend on which persona happened to load, or on whether
    one loaded at all. The same is true of the plugin block: the tools
    exist whichever persona is in front of them.
    """
    try:
        set_dir = resolve_prompt_set(name)
        content = read_prompt_file(set_dir, SYSTEM_PROMPT_FILE)
    except (OSError, ValueError) as error:
        logger.warning(
            "Persona unreadable, using built-in default | name=%s error=%s",
            name,
            error,
        )
        return _compose(DEFAULT_PROMPT, plugin_prompts)

    logger.debug(
        "System prompt loaded | name=%s dir=%s characters=%s",
        name,
        set_dir.name,
        len(content),
    )

    return _compose(content, plugin_prompts)


def load_first_message(name: str = SYSTEM_PROMPT) -> str | None:
    """
    Load the assistant's opening message for prompt set `name` from
    app/prompts/<name>/first_message.txt, or return None if the set has
    none.

    This is the greeting seeded as the first assistant turn when a
    conversation is created, so the persona has a stated direction before
    the user's first message. It follows the same all-or-nothing set
    resolution as the persona: an incomplete `name` folder falls back to
    the `default` set, and this reads `first_message.txt` from whichever
    set won. Unlike the persona there is no RESPONSE_FORMAT contract to
    attach — the text is shown to the user and read back to the model
    verbatim.

    Returns None, never raises: a set without a first message is a normal
    state, and a conversation that opens with no greeting is fine.
    """
    try:
        set_dir = resolve_prompt_set(name)
        content = read_optional_prompt_file(set_dir, FIRST_MESSAGE_FILE)
    except (OSError, ValueError) as error:
        logger.warning(
            "First message unreadable, opening with no greeting | "
            "name=%s error=%s",
            name,
            error,
        )
        return None

    if content is not None:
        logger.debug(
            "First message loaded | name=%s dir=%s characters=%s",
            name,
            set_dir.name,
            len(content),
        )

    return content


def load_title_prompt(name: str = SYSTEM_PROMPT) -> str:
    """
    Load the conversation-title instruction for prompt set `name` from
    app/prompts/<name>/title_prompt.txt, or return the built-in
    DEFAULT_TITLE_PROMPT if the set has none.

    Follows the same all-or-nothing set resolution as the persona: an
    incomplete `name` folder falls back to the `default` set, and the
    optional file is read from whichever set won. Unlike the persona there
    is no RESPONSE_FORMAT contract — the text is an internal instruction to
    a model, and its output is stored as the title, not shown to the model
    again.

    Never raises: a set without the file, or an unreadable one, both mean
    "use the default", because a conversation that could not be titled is a
    worse outcome than one titled by the generic prompt.
    """
    try:
        set_dir = resolve_prompt_set(name)
        content = read_optional_prompt_file(set_dir, TITLE_PROMPT_FILE)
    except (OSError, ValueError) as error:
        logger.warning(
            "Title prompt unreadable, using built-in default | "
            "name=%s error=%s",
            name,
            error,
        )
        return DEFAULT_TITLE_PROMPT

    if content is None:
        return DEFAULT_TITLE_PROMPT

    logger.debug(
        "Title prompt loaded | name=%s dir=%s characters=%s",
        name,
        set_dir.name,
        len(content),
    )

    return content


def _load_summary_prompt(name: str, filename: str, fallback: str) -> str:
    """
    Load one required summarization prompt (`summary_chunk_prompt.txt` or
    `summary_merge_prompt.txt`) from prompt set `name`, live.

    Same all-or-nothing set resolution as the persona: an incomplete
    `name` folder falls back to the `default` set. If even that read
    fails — a transient filesystem error, not a normal state — this
    degrades to `fallback`, the copy `settings` resolved at startup from
    the env `SYSTEM_PROMPT`, so a background summarization run never fails
    for want of a prompt.

    The returned text still contains its `{…}` placeholders; the caller
    runs `.format(...)` on it exactly as before.
    """
    try:
        set_dir = resolve_prompt_set(name)
        content = read_prompt_file(set_dir, filename)
    except (OSError, ValueError) as error:
        logger.warning(
            "Summary prompt unreadable, using the startup set's copy | "
            "name=%s file=%s error=%s",
            name,
            filename,
            error,
        )
        return fallback

    logger.debug(
        "Summary prompt loaded | name=%s file=%s dir=%s characters=%s",
        name,
        filename,
        set_dir.name,
        len(content),
    )

    return content


def load_summary_chunk_prompt(name: str = SYSTEM_PROMPT) -> str:
    """Live-load `summary_chunk_prompt.txt` for prompt set `name`."""
    return _load_summary_prompt(
        name,
        SUMMARY_CHUNK_PROMPT_FILE,
        SUMMARY_CHUNK_PROMPT,
    )


def load_summary_merge_prompt(name: str = SYSTEM_PROMPT) -> str:
    """Live-load `summary_merge_prompt.txt` for prompt set `name`."""
    return _load_summary_prompt(
        name,
        SUMMARY_MERGE_PROMPT_FILE,
        SUMMARY_MERGE_PROMPT,
    )
