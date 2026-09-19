"""What the recycling tools say to the model at runtime: tool descriptions,
refusals, and the summaries a tool returns after its table is shown.

Not to be confused with pipeline/prompts.py, which holds the instructions
the pipeline sends the *vision* model (detection, clustering, enrichment).
This file is the chat agent's side.
"""

# Tool results are English whatever the conversation is in; a model
# relaying one drifted into the wrong language in testing. Every text a
# tool returns therefore restates the rule.
_LANGUAGE = (
    "Reply in the language of the user's latest message only — one language, "
    "no translation alongside."
)

SCAN_DESCRIPTION = """\
Scan the room video or photos attached to the user's CURRENT message and \
show the estimated collectable items (counts, weight, volume) as a table. \
Call it when the user asks to scan, estimate, count or check items in an \
attached video or photos. The table is shown to the user directly; you get \
a short summary. `frames` (4-40) applies to a video only — leave it out \
unless the user asked for a specific number."""

BUILD_CATALOG_DESCRIPTION = """\
Detect items in the video or photos attached to the user's CURRENT message \
and ADD the ones not already in the item catalog. Existing rows are never \
changed. Call it as soon as the user asks, in the same turn — no \
confirmation round, the attachment is only readable now. Slow (minutes). \
The tool checks the user's role itself (admin or root) and refuses \
otherwise. `frames` (4-40) applies to a video only."""

SHOW_CATALOG_DESCRIPTION = """\
Give the user a link to the item catalog page, where they can search, \
filter and page through every row and view its evidence images. Call it \
whenever the user asks to see, open or browse the catalog; the tool checks \
the user's role itself (admin or root) and refuses otherwise. The link is \
shown to the user directly; you get the counts. To answer a question about \
the catalog's contents yourself, use recycle_query_catalog instead."""

ADMIN_ONLY = (
    "Refused: this is limited to administrators, and the current user is not "
    "one. Tell the user so; do not retry. " + _LANGUAGE
)

# The only case a result exists but the user did not see it. Should not
# happen inside a normal turn; the text still has to be true if it does.
NOT_DISPLAYED = (
    "The result could not be displayed in this reply. Tell the user to run "
    "`/recycle {subcommand}` directly with the same attachment."
)

FAILED = (
    "The tool did not produce a result. Explain this to the user in your own "
    "words, including any fix it suggests. " + _LANGUAGE + "\n\n{markdown}"
)

_TABLE_SHOWN = (
    "The full result is already displayed to the user, exactly as produced, "
    "directly above your reply. Do not repeat, re-list or recalculate its rows "
    "or numbers. In one or two sentences, point out what needs a human: items "
    "not in the catalog, low agreement, capture warnings. " + _LANGUAGE
)


def scan_summary(
    *,
    header: list[str],
    collectable: int,
    excluded: int,
    not_in_catalog: int,
    low_agreement: int,
    weight: str,
    volume: str,
) -> str:
    return (
        f"Scan complete. {' '.join(header)}\n"
        f"{collectable} collectable item type(s), {excluded} excluded by catalog, "
        f"{not_in_catalog} not in catalog, {low_agreement} low-agreement. "
        f"Totals: {weight}, {volume}.\n\n{_TABLE_SHOWN}"
    )


def build_summary(*, header: str, review_notes: int) -> str:
    return (
        f"Catalog build complete. {header} {review_notes} note(s) for review "
        "are listed in the result. Remind the user the catalog must be "
        f"reviewed by hand.\n\n{_TABLE_SHOWN}"
    )


def show_catalog_summary(*, total: int, collectable: int, excluded: int) -> str:
    return (
        f"Catalog shown: {total} item(s), {collectable} collectable, "
        f"{excluded} excluded.\n\n{_TABLE_SHOWN}"
    )


# ---- catalog knowledge: query and edit --------------------------------

QUERY_CATALOG_DESCRIPTION = """\
Run ONE read-only SQL query (SELECT, or WITH ... SELECT) over the item \
catalog and get the rows back, to count, search or check it. The tool \
checks the user's role itself (admin or root).
View `recycling_catalog`, one row per catalog item:
id text (stable key) | canonical_label text | aliases text[] (other names \
that match this row) | visual_class text | excluded bool | exclusion_reason \
text | observations int (times seen while building) | weight_kg, \
weight_kg_min, weight_kg_max float (kg, one unit) | length_cm, width_cm, \
height_cm float (bounding box, cm) | volume_m3 float (set only when not the \
box) | material text | nestable, stackable bool | unit_price float | \
currency text | extra jsonb (string values) | source text \
('llm_estimate'|'measured'|'client_supplied'|'unknown') | updated_at timestamptz.
NULL means unknown. Returns at most 200 rows or 20,000 characters and says \
when it cut. 5-second limit. similarity(a, b) from pg_trgm may be available \
for near-duplicate labels."""

_ITEM_FIELDS_NOTE = (
    "Only the fields you put in changes/values are set; null clears a field. "
    "id, observations and updated_at are managed by the system. "
    "The tool checks the user's role itself (admin or root)."
)

CREATE_ITEM_DESCRIPTION = (
    "Add ONE new row to the item catalog. Its id is derived from "
    "canonical_label. To base it on an existing row, pass copy_from_id: every "
    "value is copied except id, aliases and observations, then your fields "
    "override. The new row is shown to the user exactly. " + _ITEM_FIELDS_NOTE
)

UPDATE_ITEM_DESCRIPTION = (
    "Change ONE existing catalog row, named by item_id. aliases and extra "
    "replace the whole list/map. The before/after is shown to the user "
    "exactly. " + _ITEM_FIELDS_NOTE
)

DELETE_ITEM_DESCRIPTION = (
    "Delete ONE catalog row, named by item_id. The removed row is shown to "
    "the user exactly. Scans can no longer match anything to it. The tool "
    "checks the user's role itself (admin or root)."
)

QUERY_DISABLED = (
    "Catalog queries are not available on this server (the agent database "
    "role is disabled or failed to start; details are in the server log). "
    "Tell the user. " + _LANGUAGE
)

QUERY_FAILED = (
    "The query failed. Fix it and try again if the fix is clear; otherwise "
    "tell the user. Error: {error}"
)

EDIT_REJECTED = (
    "Nothing was changed: {reason} Explain this to the user, or correct the "
    "call if the fix is clear. " + _LANGUAGE
)

EDIT_NOT_DISPLAYED = (
    "The change WAS saved, but could not be displayed in this reply. Tell the "
    "user exactly what changed: {detail} " + _LANGUAGE
)

_CHANGE_SHOWN = (
    "The change is already displayed to the user, exactly, directly above your "
    "reply. Confirm it in one sentence; do not repeat the table. " + _LANGUAGE
)


def edit_summary(*, action: str, item_id: str, detail: str) -> str:
    return f"{action} `{item_id}`: {detail}\n\n{_CHANGE_SHOWN}"


def catalog_link_summary(*, total: int, collectable: int, excluded: int) -> str:
    return (
        f"A link to the catalog page is displayed to the user, directly above "
        f"your reply. The catalog has {total} item(s): {collectable} "
        f"collectable, {excluded} excluded. Its rows are not in your context. "
        "In one sentence, tell the user they can open it there; do not repeat "
        "the link. " + _LANGUAGE
    )


def catalog_shown_placeholder(*, total: int) -> str:
    """What later turns remember instead of the catalog table itself."""
    return (
        f"[The full item catalog ({total} rows) was shown to the user here. "
        "It is not in your context: use recycle_query_catalog to look "
        "anything up.]"
    )
