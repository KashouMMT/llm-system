# recruitment

The largest plugin: the whole recruitment vertical — interviewing a job
seeker, validating what they gave, and producing 履歴書 (rirekisho) and
職務経歴書 (shokumu keirekisho) — with its schemas, layout, rendering,
templates, and the one-off scripts that built those templates. Two tools,
`generate_rirekisho` and `generate_shokumu_keirekisho`, are the only thing
the model calls; everything else in this folder exists to make those two
calls correct.

Named for the business domain, not for the file format it emits. It was
called `documents` until the recycling plugin made that name misleading —
that plugin writes files too, and "documents" read as though any
file-producing feature belonged here.

**Where the domain knowledge lives.** `plugin_prompt.txt` holds what the
model needs to know before it decides to call anything: the seven
interview steps, the pre-generation checks, when to call each tool, and
the blank forms. All of it used to sit in `app/prompts/anna/system_prompt.txt`,
where it was sent even to a deployment that had named this plugin in
`EXCLUDED_TOOL_PLUGINS`. The persona file now describes only who Anna is
and how she behaves; what she can *do* comes from here, and disappears
with the plugin.

## Files

| File / folder | Contents |
|---|---|
| `__init__.py` | `PLUGIN` — exposes both tools via `make_document_tools`, injects `plugin_prompt.txt` |
| `plugin_prompt.txt` | Injected into the system prompt while the plugin is loaded: interview steps, validation, document generation, blank forms |
| `prompts.py` | Runtime text: the two tool descriptions and the post-generation message |
| `tools.py` | The two tools, built from one shared closure factory (validate → render → store → record) |
| `schemas_rirekisho.py` | `Rirekisho` and its nested types — doubles as `generate_rirekisho`'s `args_schema`, so every field description is prompt text |
| `schemas_shokumu.py` | `ShokumuKeirekisho` — imports `YearMonth`/`KANA_PATTERN` from `schemas_rirekisho` rather than restating them |
| `dates.py` | 西暦→和暦 conversion, 満年齢 — document-specific date formatting only; the application-wide `JST`/`today_in_japan()` lives in `app/utils/jst.py` |
| `blank.py` | `BLANK_DOCUMENTS` — placeholder payloads the API can hand the frontend |
| `layouts/rirekisho_jis.py` | The JIS 履歴書 form's cell map and capacity model (font shrink, `LayoutOverflow`) |
| `renderers/` | `base.py` (the `Renderer` protocol), `xlsx_renderer.py`, `docx_renderer.py`, `ooxml.py` (restores the photo-box drawing `openpyxl` drops on save) |
| `templates/` | `rirekisho.xlsx`, `shokumu_keirekisho.docx` — the blank forms rendering fills in |
| `scripts/` | `make_rirekisho_template.py`, `make_shokumu_template.py` — build the blank templates from client-approved samples; run by hand, not part of the loaded application |

## What each tool does

Validate the model's arguments a second time through the Pydantic schema
(LangChain already checked them against `args_schema`, but that pass turns
a dict back into a typed object — the only guarantee that what gets
rendered is what passed validation), render through the document's
`Renderer`, write bytes to `FileStorage`, then record a `files` row.
Bytes are written **before** the row: the reverse order can leave a row
pointing at bytes that don't exist (a download the user watches fail);
this order can only leave an unreferenced blob (invisible, sweepable).

Identity (`thread_id`, `assistant_message_id`) comes from the run
configuration, never from the tool's own arguments — a conversation id a
model supplied could name someone else's conversation.

## Validators enforce format, never completeness

Every validator returns early on an empty value. A blank field means the
user chose not to supply it, and a 履歴書 printed with blanks is a normal
way to use the form — only a value that is *present and malformed* is an
error. `address_kana` accepting digits and hyphens where `name_kana` does
not (Japanese address furigana carries block numbers as numerals) is the
case that made this distinction matter in practice: the stricter rule,
applied uniformly, rejected correct input.

## Capacity is a hard constraint for the xlsx path only

A printed 履歴書 has as many ruled lines as it has. `layouts/rirekisho_jis.py`
measures text in Excel's half-width units and applies two caps: overflow
steps the font down (fine — the reader sees smaller text); overflow that
still doesn't fit at the smallest readable size raises `LayoutOverflow`,
which reaches the assistant through `ToolNode`'s error handler and becomes
a question to the user, in Japanese. The `.docx` path has no equivalent —
a Word document paginates itself.
