# recycling

`/recycle` — the recyclable-item scanner. Today it has only slash
commands and no tools. That is a stage, not the design: the plugin is
heading toward agent tools (see **Direction: agent tools** below).
**Must be named in `EXCLUDED_TOOL_PLUGINS` on the deploy branch** — the
production job-application service must never load it, and once the
plugin has tools that exclusion is the only thing keeping them out of the
`anna` persona's tool schema. See
`documentation/claude/Recycling_Estimator_TODO.md`, the context-restore
document this plugin is built from; read that before changing anything
here.

## Files

| File / folder | Contents |
|---|---|
| `__init__.py` | `PLUGIN` — `initialize` creates the catalog table; builds one `openai` client at startup (from `ToolContext.llm`, overridable by `RECYCLING_VISION_MODEL`), registers `/recycle`, exposes no tools yet |
| `commands.py` | Subcommand dispatch, attachment handling, Markdown rendering, the durable-context file attachment |
| `runner.py` | Async glue the pipeline itself doesn't have — fires consensus runs concurrently via `asyncio.to_thread` |
| `database/` | Everything this plugin does with Postgres — see **Catalog storage** |
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

Declared once as `SUBCOMMANDS` (`SubcommandSpec`s) in `commands.py`; the
system prompt's SLASH COMMANDS block, the unknown-command reply and
`GET /commands` are all generated from it. **Every catalog command —
`build_catalog`, `build_catalog_force`, `show_catalog` — is
`admin_only`**: the build commands write the catalog, which every scan
matches against and a reviewer corrects by hand, and `show_catalog`
exposes that staff data. `ChatService` refuses them for any other user;
`scan` is the only subcommand open to everyone.

| Command | Does |
|---|---|
| `/recycle scan [frames]` | One room video **or** one or more photos (`_attached_media` decides; the app refuses a video sent with anything else). **Photos:** non-images ignored and *reported*, `runner.scan` against the catalog. **Video:** `runner.scan_video` → core `extract_frames` (ffmpeg keyframes; blurry/dark/overexposed/blank/duplicate frames dropped and counted; portrait/short/low-res/glare warned; refused under 4 usable frames with a remedy) → the same `scan`; header states frames used, skipped per reason, warnings — above the table. `frames` = 4–40, default 12, video only (an error with photos, not ignored). Renders every section: Collectable, Totals, Excluded by catalog, Not in catalog, Low agreement. JSON carries `source` (`video` / `images`) and, for video, `frame_check`. `scan_image` and `scan_video` are aliases of this handler |
| `/recycle build_catalog [frames]` | Same video-or-photos input as `scan`. Runs harvest → cluster → enrich → assemble, then **merges additively**: new items are added, but anything that already matches an existing catalog row (by canonical label or alias) is left completely untouched. Safe to run repeatedly without eroding hand-reviewed data |
| `/recycle build_catalog_force` | Same pipeline, but a match **replaces** the existing row instead of being skipped — the newer scan's canonical label, metadata, and excluded/exclusion_reason win. The existing row's `id` is kept (nothing referencing it breaks), aliases are the union of old and new, and `observations` is summed rather than reset |
| `/recycle show_catalog` | Renders the current catalog as a Markdown table — no LLM call |

Both build commands tolerate an empty catalog — an empty table is an
empty catalog, so the very first build bootstraps one rather than
erroring. See `pipeline/build.py`'s `merge_into_catalog` for the exact
merge rules.

`edit_catalog` as a slash command was scoped and deliberately **not
built**. Editing the catalog from chat is now planned as an admin-only
agent tool instead (see **Direction: agent tools**). Until that exists,
edit rows in the table directly (psql).

## Catalog storage

The catalog is the Postgres table `recycling_catalog_items`, owned by this
plugin: `database/schema.py` creates it from the `initialize` hook, not
core `app/database/init_db.py` — the plugin-wide convention that a
plugin's database code lives in its own `database/` folder.

| Choice | Why |
|---|---|
| One typed column per `ItemMetadata` field; only `extra` is JSONB | Catalog-analysis tools and a review UI filter on weight, material and the rest; a blob hides them |
| `aliases TEXT[]`, no uniqueness constraint | A contested alias must reach a reviewer (`Catalog` raises on load), not be silently rejected by the database |
| Primary key `(tenant, id)`, one `'default'` tenant today | The catalog is meant to be per-client; adding the column later means a key change and a filter in every query |
| `position` column | Keeps build order, the order `show_catalog` has always listed |
| `CatalogRepository.save` replaces the tenant's whole catalog in one transaction | `merge_into_catalog` already returns the complete merged catalog; a failed write leaves the old catalog intact |
| No seed file | The table is the only catalog. A fresh database starts empty and `/recycle build_catalog` fills it. Two sources of truth (a file and a table) would need syncing on every edit |

`CatalogRepository` speaks `Catalog` in and out, so the pipeline and the
commands never see rows. **Why the move:** the catalog used to be a
`catalog.json` inside the container image, so every redeploy destroyed any
catalog built on the server. That file is gone.

**Failures.** `CatalogRepository` logs every failed query (and any row
that no longer validates) with `logger.exception` — table, tenant, and for
a save the item count — then raises `CatalogStorageError`. The commands
turn that into one line in chat with no database detail; `build_catalog`
additionally says the build ran but was **not saved**, since that build
cost real API calls. A failure creating the table at startup is logged by
the plugin loader, and the plugin is then left out entirely.

A schema change: edit `CREATE TABLE` in `database/schema.py`, drop the
table (the database is disposable), restart, rebuild.

## Why every data-producing command also attaches a file

`scan` and `build_catalog` write their full structured result as a
`text/plain` file on the assistant message, alongside the Markdown reply.
`read_attachment` (core, `app/attachments/`) already reads text
files back — no new tool was needed. The reason: a long conversation gets
summarized, and a scan result folded into a paraphrase is exactly the
failure this project's one rule (nothing detected is ever dropped without
the reviewer seeing it) exists to prevent. The attached file survives
summarization; the model can re-read it on demand days later.

## Direction: agent tools

The reason this pipeline lives inside `llm-system` as a plugin at all,
rather than as its own project, is to reach the agentic loop. That is the
direction now, not a someday. It has two goals:

1. **Run the recycle commands from free text.** "Scan this video for me"
   → the model calls a tool that runs the same handler `/recycle scan`
   runs. The model decides the intent. The tool checks the preconditions
   in code: if no media is attached, the tool returns a fixed message
   rather than the model deciding. The same goes for `build_catalog` and
   `show_catalog`.
2. **Know the catalog.** The catalog will outgrow hand review, so an admin
   can ask the model to count rows, find duplicates, and flag labels,
   weights or metadata that look wrong. Then, when asked, the model can
   correct them.

What does not change: **a scan's table still reaches the user exactly as
rendered.** A model asked to relay a 40-row table can drop a row or alter a
number. So when a tool produces the table, code writes the table into the
assistant message and the model gets only a short summary to comment on.
The slash commands stay as the direct, no-LLM path to the same handlers.

Catalog tools that read or write staff data are **admin-only**, checked
inside the tool against the user taken from the run configuration, never
from a tool argument.

The first step, moving the catalog into Postgres, is done (see **Catalog
storage**). The phase plan and its open questions are in
`documentation/claude/Recycling_Agent_Tools_Plan.md`.

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
oversight: see `documentation/claude/Recycling_Estimator_TODO.md` §12 for
why standalone usability was never the goal.
