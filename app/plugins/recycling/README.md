# recycling

`/recycle` — the recyclable-item scanner. No tools at all, only slash
commands: a scan never enters the model's tool schema, by design, so this
plugin cannot confuse the `anna` persona even when both are loaded in the
same deployment. **Must be named in `EXCLUDED_TOOL_PLUGINS` on the deploy
branch** — the production job-application service must never load it. See
`documentation/other/Recycling_Estimator_TODO.md`, the context-restore
document this plugin is built from; read that before changing anything
here.

## Files

| File / folder | Contents |
|---|---|
| `__init__.py` | `PLUGIN` — builds one `openai` client at startup (from `ToolContext.llm`, overridable by `RECYCLING_VISION_MODEL`), registers `/recycle`, exposes no tools |
| `commands.py` | Subcommand dispatch, attachment handling, Markdown rendering, the durable-context file attachment |
| `runner.py` | Async glue the pipeline itself doesn't have — fires consensus runs concurrently via `asyncio.to_thread` |
| `catalog.json` | The catalog. `build_catalog`/`build_catalog_force` merge into this file; `show_catalog` reads it |
| `pipeline/` | The detection pipeline — see below |

`pipeline/` was originally prototyped as a standalone `playground/` folder
outside the app, with its own CLIs (`detect.py`, `estimate.py`,
`build_catalog.py`) for testing the pipeline with no server, database, or
login needed. That folder has since been **removed entirely** — the point
of this plugin was always to bring the pipeline into the agentic loop, not
to keep it usable standalone, so once the logic lived here the CLI-only
path stopped earning its keep. `labels.py`, `catalog.py`, `resolve.py`,
`consensus.py` (its `merge_runs` untouched — it is pure and encodes
per-run synonym merging that took several bug fixes to get right) carried
their logic across unchanged when they moved; only their internal imports
became absolute (`app.plugins.recycling.pipeline.x`). `vision.py`
additionally has bytes-based entry points (`encode_image_bytes`,
`detect_items_bytes`) alongside `Path`-based ones, since the plugin gets
image bytes from `FileStorage` and never has a filesystem path. `build.py`
is the harvest/cluster/enrich/assemble logic, called by `/recycle
build_catalog`.

## Commands

| Command | Does |
|---|---|
| `/recycle scan_image` | Reads this message's image attachments (ignoring and *reporting* any non-images — nothing is dropped silently), runs `runner.scan` against the catalog, renders every section: Collectable, Totals, Excluded by catalog, Not in catalog, Low agreement |
| `/recycle scan_video` | Registered, **not implemented** — answers explaining why (needs OpenCV keyframe sampling, TODO §11a/phase 7) |
| `/recycle build_catalog` | Runs harvest → cluster → enrich → assemble over this message's attached images, then **merges additively**: new items are added, but anything that already matches an existing catalog row (by canonical label or alias) is left completely untouched. Safe to run repeatedly without eroding hand-reviewed data |
| `/recycle build_catalog_force` | Same pipeline, but a match **replaces** the existing row instead of being skipped — the newer scan's canonical label, metadata, and excluded/exclusion_reason win. The existing row's `id` is kept (nothing referencing it breaks), aliases are the union of old and new, and `observations` is summed rather than reset |
| `/recycle show_catalog` | Renders the current catalog as a Markdown table — no LLM call |

Both build commands tolerate `catalog.json` not existing yet — a missing
file is treated as an empty catalog, so the very first build bootstraps
one rather than erroring. See `pipeline/build.py`'s `merge_into_catalog`
for the exact merge rules.

`edit_catalog` was scoped and deliberately **not built**: a real review UI
(TODO §12 phase 5, a `.tsx` settings page) is the next planned piece of
work, and a free-text chat editor for structured catalog rows would be
replaced almost immediately. Catalog edits go through `catalog.json` by
hand, or through that UI once it exists.

## Why every data-producing command also attaches a file

`scan_image` and `build_catalog` write their full structured result as a
`text/plain` file on the assistant message, alongside the Markdown reply.
`read_attachment` (from the `attachments` plugin) already reads text
files back — no new tool was needed. The reason: a long conversation gets
summarized, and a scan result folded into a paraphrase is exactly the
failure this project's one rule (nothing detected is ever dropped without
the reviewer seeing it) exists to prevent. The attached file survives
summarization; the model can re-read it on demand days later.

## Why commands today, and tools later

A command is deterministic: `ChatService` routes it straight to a handler
before the agent graph ever runs, and the handler's return value is
written as the assistant message verbatim. A model asked to relay a
40-row table can drop a row or alter a number — routing a scan through the
LLM would reintroduce exactly the risk this design avoids, so a scan's own
result rendering should stay a command indefinitely.

But commands are not the end state for the whole plugin. The reason this
pipeline lives inside `llm-system` as a plugin at all — rather than as its
own standalone project — is to eventually reach the agentic loop: catalog
CRUD, and anything that needs judgment or a back-and-forth with the user
(e.g. "is this scanned item actually recyclable, or should it be
excluded?"), is headed toward becoming real tools `AgentGraph` calls, the
same way `generate_rirekisho` is a tool today. Deterministic vs. tool is a
per-feature decision, not a blanket rule: does dropping or rephrasing a
value matter (command), or does the step genuinely need reasoning or
conversation (tool).

## Model and credentials

`__init__.py` builds one raw `openai.OpenAI` client at plugin-load time,
from `ToolContext.llm` (the app's own `MODEL_NAME`/`LLM_API_KEY`/
`LLM_BASE_URL`) — no second configuration to keep in sync — optionally
overridden by `RECYCLING_VISION_MODEL` for the day the chat model is
downgraded for cost while scanning still needs vision. The raw SDK, not
`ToolContext.chat_model` (LangChain): `vision.py`'s structured-output
`.parse()` call is the part of the pipeline most likely to break in a
LangChain rewrite, and it moved across unchanged on purpose.

## There is no standalone way to run this anymore

`playground/` (the original prototype folder — `detect.py`, `estimate.py`,
`build_catalog.py`, `probe_multiview.py`, and the small dedup experiment
from TODO §11a) has been deleted. Testing any part of the pipeline now
means running the full app (`python -m app.main --api`) and going through
`/recycle` in a real conversation. This was a deliberate trade, not an
oversight: see `documentation/other/Recycling_Estimator_TODO.md` §12 for
why standalone usability was never the goal.
