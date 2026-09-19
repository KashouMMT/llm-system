"""
Every rendering of the slash-command list, from PluginCommand.subcommands.

Three readers need the same list — the model (a SLASH COMMANDS block in
the system prompt), a user who typed a wrong command (the reply), and the
frontend's autocomplete (GET /commands). Before this module each kept a
hand-written copy, and renaming one subcommand meant finding all of them.
Now a plugin declares SubcommandSpecs once and these functions are the
only place a list is written.

A plain module, not a plugin: the loader ignores non-package files in
app/plugins/, and plugins may import it the same way they import
contracts.py.
"""

from collections.abc import Iterable, Mapping

from app.plugins.contracts import PluginCommand, SubcommandSpec

COMMANDS_PROMPT_HEADER = "SLASH COMMANDS"


def _invocation(namespace: str, spec: SubcommandSpec) -> str:
    return " ".join(part for part in (f"/{namespace}", spec.name, spec.usage) if part)


def _visible(
    command: PluginCommand,
    include_admin: bool,
) -> list[SubcommandSpec]:
    return [spec for spec in command.subcommands if include_admin or not spec.admin_only]


def render_subcommand_lines(
    namespace: str,
    specs: Iterable[SubcommandSpec],
) -> str:
    """Markdown bullets, one per subcommand — the human-facing listing."""
    lines = []

    for spec in specs:
        line = f"- `{_invocation(namespace, spec)}` — {spec.summary}"
        if spec.attachments:
            line += f" Attach: {spec.attachments}."
        if spec.admin_only:
            line += " *(admin only)*"
        lines.append(line)

    return "\n".join(lines)


def render_command_list(
    commands: Mapping[str, PluginCommand],
    *,
    include_admin: bool,
) -> str:
    """
    Every command a user may run, for a reply to an unknown command.
    Admin-only subcommands are left out for a non-admin rather than listed
    and then refused.
    """
    blocks = []

    for namespace in sorted(commands):
        specs = _visible(commands[namespace], include_admin)

        if specs:
            blocks.append(render_subcommand_lines(namespace, specs))
        elif not commands[namespace].subcommands:
            # A plugin that declares no specs still has a namespace.
            blocks.append(f"- `/{namespace}`")

    return "\n".join(blocks)


def render_command_prompt(commands: Mapping[str, PluginCommand]) -> str:
    """
    The system-prompt block, or "" when no loaded plugin declares a
    subcommand.

    Composed from the commands actually loaded, so an excluded plugin's
    commands are never described — the same guarantee plugin_prompt.txt
    gets from load_plugin_prompts. What a command is *for* and when to
    suggest it stays in that plugin's plugin_prompt.txt; this block is only
    the facts a spec can carry.

    The prompt is built once per deployment, not per user, so the model
    cannot know whether it is talking to an admin. Admin-only commands are
    listed and marked instead of hidden, with the rule for mentioning them.
    That rule must not make the model gatekeep: an earlier wording ("suggest
    one only to someone who says they manage this system") made it refuse
    a real admin's plain request and point at the command instead of
    calling the equivalent tool. The system enforces the role; the model
    only avoids advertising.
    Aliases are deliberately omitted: the model should teach the current
    name.
    """
    lines = []

    for namespace in sorted(commands):
        for spec in commands[namespace].subcommands:
            line = f"- `{_invocation(namespace, spec)}` — {spec.summary}"
            if spec.attachments:
                line += f" Attach: {spec.attachments}."
            if spec.admin_only:
                line += " (admin only)"
            lines.append(line)

    if not lines:
        return ""

    return "\n".join(
        [
            COMMANDS_PROMPT_HEADER,
            "",
            "The user runs one of these by sending it as the whole message,",
            "with any attachments it names. You cannot run a command yourself",
            "and never produce its output — but where one of your tools does",
            "the same job, call the tool instead of telling the user to type",
            "the command. Only the commands below exist — never invent a",
            "subcommand or an argument.",
            "",
            "Commands marked (admin only) are refused by the system for anyone",
            "who is not an administrator; the admin and root roles both count",
            "as administrator. You cannot see the user's role, so never refuse,",
            "question or second-guess a user over it — the system checks. Do",
            "not bring admin-only commands up unprompted; when a user asks for",
            "one, act on it.",
            "",
            *lines,
        ]
    )


def describe_commands(
    commands: Mapping[str, PluginCommand],
    *,
    include_admin: bool,
) -> list[dict]:
    """GET /commands payload: plain data for the frontend's autocomplete."""
    described = []

    for namespace in sorted(commands):
        specs = _visible(commands[namespace], include_admin)

        if not specs:
            continue

        described.append(
            {
                "namespace": namespace,
                "subcommands": [
                    {
                        "name": spec.name,
                        "usage": spec.usage,
                        "summary": spec.summary,
                        "attachments": spec.attachments,
                        "aliases": list(spec.aliases),
                        "admin_only": spec.admin_only,
                    }
                    for spec in specs
                ],
            }
        )

    return described
