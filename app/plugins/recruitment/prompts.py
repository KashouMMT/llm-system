"""
Every piece of model-facing text this plugin says at runtime.

The split this module exists for: text injected into the *system prompt*
lives in a plugin_prompt.txt beside the plugin's __init__.py and is paid
for on every turn. This plugin deliberately has no such file — when and
how to build a 履歴書 is the `anna` persona's subject, already stated in
app/prompts/anna/system_prompt.txt, and repeating it here would pay for
the same instruction twice on every request.

What is here is said only when a tool is described or called: the two
tool descriptions, which ride along with the schemas as part of the tool
definition, and the success message the model reads afterwards.

Both descriptions are prompt text, not documentation. They are sent on
every call alongside every field description in the corresponding schema,
which is also why they do not belong in anna.txt: there they would be
paid for on turns that have nothing to do with documents.
"""

RIREKISHO_DESCRIPTION = """\
Generate a 履歴書 (rirekisho) file the user can download.

Call this ONLY when all of the following are true:
- The user has explicitly asked for their 履歴書 to be created.
- You have confirmed every required field with the user in conversation.
- You are not guessing, inferring, or filling in any value yourself.

Do NOT call this to draft, preview, or discuss a 履歴書 — write that as a
normal reply instead. This tool produces a finished file, so calling it
early produces a document with wrong information in it.

If a required field is missing, do not call this tool. Ask the user for the
missing information first.
"""

SHOKUMU_KEIREKISHO_DESCRIPTION = """\
Generate a 職務経歴書 (shokumu keirekisho, detailed work history) file the
user can download.

Call this ONLY when all of the following are true:
- The user has explicitly asked for their 職務経歴書 to be created.
- You have confirmed every required field with the user in conversation.
- You are not guessing, inferring, or filling in any value yourself.

Do NOT call this to draft, preview, or discuss a 職務経歴書 — write that as
a normal reply instead. This tool produces a finished file, so calling it
early produces a document with wrong information in it.

If a required field is missing, do not call this tool. Ask the user for the
missing information first.
"""

# Read by the model and likely to be quoted in its reply. The link ban is
# not decoration: told only that a file "is attached", the model will
# build a plausible download path around the filename — a first test run
# produced "sandbox:/mnt/data/...", a convention from its training data
# that points nowhere in this application. The real download comes from
# the message attachment, so any link it writes is broken by construction.
GENERATED = (
    "{display_name} generated successfully as {filename}. The download is "
    "attached to this message automatically and the user can already see "
    "it. Tell them it is ready, in one or two sentences. Never write a "
    "link, URL, file path, or download button of your own — any link you "
    "write will be broken. Do not repeat the document's contents."
)
