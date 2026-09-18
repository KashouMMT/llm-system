# Recycling → agent tools: phase plan

Status 2026-09-18: **phase 1 code written, awaiting user live test**; phases 2–5 not started. Phase 1 as built: `ToolContext.db_pool`, `ToolPlugin.initialize` + `loader.initialize_plugins` (failed init → added to exclusion set in Application), `recycling/database/{schema,catalog_repository}.py`, table has extra `position` col (build order). Catalog `version` not stored (always 1). Verified statically: compile, full import, row↔model round-trip of all 259 seed rows. NOT verified: anything against a live DB.
2026-09-18 revision (user): **catalog.json deleted (git rm), no seed** — table is sole source; fresh DB = empty catalog, rebuild via build_catalog. `Catalog.load/save(path)` removed from pipeline/catalog.py; `CatalogFile` kept only for the attached snapshot (renamed `recycle_catalog_snapshot.json`). DB failures: CatalogRepository logs (`logger.exception`, table/tenant/items) → `CatalogStorageError`; commands return `_STORAGE_FAILED` one-liner (build adds "not saved"). `count()`/`seed_if_empty` removed. TODO.md's many `catalog.json` mentions are historical.
Supersedes the "Seed" bullet below. Decisions behind it: `Recycling_Estimator_TODO.md` (2026-09-18 note under §12 entry-point row).

## Fixed decisions
- Order: catalog→Postgres FIRST, then identity/output plumbing, then goal 1 (command tools), then goal 2 (catalog knowledge), then permission modes.
- Scan/build table reaches user verbatim: tool hands rendered MD to ChatService (option B, framework-free collector keyed by assistant_message_id); model gets a summary line only. Not LangGraph stream_writer (lock-in).
- Identity (user_id, is_admin) → run config `configurable`, set by ChatService. Never tool args.
- Tools bound once at startup (graph.py:114) → every user sees every tool; admin check INSIDE each tool. Per-user tool menus deferred.
- Confirmation baseline = plugin_prompt.txt rule ("state what you'll do, wait for yes") for costly/writing tools. Later → Manual / Accept-edits / Auto modes enforced in code (user wants Claude-Code-like modes).
- Reads: raw SELECT allowed. Guard = DB permissions, not string checks (`WITH x AS (DELETE…) SELECT`, pg_sleep, pg_read_file bypass text filters). Writes: typed `update_catalog_item(item_id, changes)`, Pydantic-validated, one row, before→after diff. Never raw UPDATE (missing WHERE = whole table).

## Phase 1 — catalog.json → Postgres (no behaviour change)
- ToolContext += `db_pool: AsyncConnectionPool` (app/database/connection.py create_pool). ToolPlugin += optional async `initialize(ctx)` hook; Application awaits after pool opens.
- `recycling/catalog_repository.py`: ensure_schema(), load()->Catalog, save(Catalog) (whole replace, one txn — matches merge_into_catalog returning a full Catalog), count(). Domain `Catalog`/`CatalogItem` unchanged; repo maps rows↔models.
- Table `recycling_catalog_items`: PK (tenant, id); tenant text default 'default'; canonical_label, visual_class, aliases text[], excluded bool, exclusion_reason, observations int, every ItemMetadata field as typed column, extra jsonb, source, updated_at. No UNIQUE on aliases (contested aliases must be reported, not rejected).
- **Convention (user, 2026-09-18): everything a plugin needs for the DB lives in `app/plugins/<name>/database/`** (DDL, repositories, grants). Here: `recycling/database/schema.py` (DDL + grant to agent role), `recycling/database/catalog_repository.py`. Run from the `initialize` hook — not core init_db.py. Deleting the plugin leaves the table; accepted (DB disposable). Add convention to README Tool plugins section in phase 1.
- tenant column kept (user agreed, 2026-09-18).
- Seed: table empty at startup → import catalog.json. JSON = seed only after this.
- commands.py: `_load_catalog_or_empty`/`CATALOG_PATH` save → repository.
- Verify (user): show_catalog = 259 rows; scan unchanged; build_catalog persists across restart; drop table → reseeds.

## Phase 2 — core plumbing
- ChatService → graph config: user_id, is_admin. Core helper to read identity + require admin from RunnableConfig.
- Reply-block collector: tool publishes deterministic MD; ChatService streams it into the reply + persists in assistant message. UNREAD: current SSE/stream code — read before designing.
- Tool builds CommandContext from config (conversation_id, user, current_user_message_id, assistant_message_id) → reuse command handlers unchanged.

## Phase 3 — goal 1: command tools
- Slice order: `recycle_show_catalog` (no media, no LLM cost — proves plumbing) → `recycle_scan(frames?)` → `recycle_build_catalog(frames?)`.
- build_catalog_force: **command-only (agreed)**. On a force request the model suggests `/recycle build_catalog_force` and warns it overwrites matching (hand-reviewed) rows — plugin_prompt.txt rule.
- Preconditions in code: no media → fixed msg; non-admin → refusal.
- prompts.py = tool descriptions; plugin_prompt.txt rewritten (tools exist; confirm before build; admin-only note).

## Phase 4 — goal 2: catalog knowledge
- `query_catalog(sql)`: admin-only; READ ONLY txn; statement_timeout ~5s; row cap ~200; schema in tool description.
- Agent role (user design, 2026-09-18): CORE `app/database/agent_role.py` creates LOGIN role at startup (admin sync conn, like init_db) — CONNECT + schema USAGE, zero table grants. Env `DB_AGENT_USER`/`DB_AGENT_PASSWORD` (README + deploy/README). Core gives a separate small pool/conn as that role. Plugin `database/schema.py` does `GRANT SELECT ON recycling_catalog_items TO <agent role>`.
- **Must be a separate LOGIN connection, NOT `SET ROLE` on the main pool**: main DB_USER=postgres (superuser locally) → model SQL `RESET ROLE` / `set_config('role',…)` escapes back to superuser. Grants are the real guard; read_only/statement_timeout are user-settable GUCs → defense in depth only. Single statement only (extended protocol; verify psycopg3 behaviour).
- Local DB_USER=postgres = superuser → can CREATE ROLE. Server DB user: check deploy/README before phase 4.
- `update_catalog_item(item_id, changes)`: repo gets per-row update; validation via ItemMetadata; diff returned; confirm rule in prompt.

## Phase 5 — permission modes (later)
- Per-conversation mode (manual / accept-edits / auto); tools classified read / write / costly; enforcement in tool code, not prompt. Manual → tool returns "confirmation required" + pending action; user yes/UI button executes. Decide then: own pending-action table vs LangGraph interrupt (lock-in).
