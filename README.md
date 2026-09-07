# llm-system

A conversational LLM system built on LangChain and LangGraph, with PostgreSQL-backed persistence and rolling summarization for long-running conversations. The model provider is selectable at startup (`LLM_PROVIDER`): a local Ollama instance, or any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq, DeepSeek). Runs as a CLI or a FastAPI server, with a React + TypeScript frontend in `ui/` that receives tokens over Server-Sent Events.

Its current application is Japanese job-application documents: the `anna` persona interviews the user for the facts a 履歴書 (rirekisho) and a 職務経歴書 (shokumu keirekisho) require, and one tool per document renders the confirmed data to a downloadable file attached to the assistant's message. Both render to the formats an employer actually receives — the 履歴書 as `.xlsx` filling a JIS-style form, the 職務経歴書 as `.docx` — built from client-approved reference documents in `documentation/other/`.

## Requirements

- Python 3.11+
- PostgreSQL (reachable instance; the app creates its database and tables on startup if they don't exist)
- One model provider: either [Ollama](https://ollama.com) running locally with the target model pulled, or an API key for an OpenAI-compatible endpoint
- Node.js 20+ (frontend only)

## Setup

```bash
pip install -r requirements.txt
```

Configure via a `.env` file. `DB_PASSWORD` is **required** — it has no usable default and startup fails if it is empty. `LLM_API_KEY` is required when `LLM_PROVIDER=openai`. Everything else is optional (defaults shown).

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` or `openai`. Selects which factory in `app/llm/` builds the client |
| `MODEL_NAME` | `qwen3.5:4b` | Model identifier for the selected provider (e.g. an Ollama tag, or `deepseek/deepseek-chat-v3.1:free` on OpenRouter) |
| `SYSTEM_PROMPT` | `default` | Name of a folder under `app/prompts/` holding the prompt set (`system_prompt.txt` + the two summary prompts); the whole set falls back to `app/prompts/default/` if any of the three files is missing or empty |
| `TEMPERATURE` | `0.3` | Sampling temperature. Deliberately low — this assistant must not invent facts it was not given |
| `MAX_TOKENS` | `2048` | Max tokens generated per response (`num_predict` on Ollama, `max_tokens` on OpenAI) |
| `TOP_P` | `0.9` | Nucleus sampling |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | **Ollama only.** Ollama server address |
| `CONTEXT_WINDOW` | `16384` | **Ollama only** (`num_ctx`). The system prompt alone is ~2,800 tokens, and Ollama truncates from the *front* — too small a window silently drops the system prompt |
| `TOP_K` | `40` | **Ollama only.** Top-k sampling |
| `LLM_API_KEY` | *(empty)* | **OpenAI-compatible only.** Required when `LLM_PROVIDER=openai` |
| `LLM_BASE_URL` | *(empty)* | **OpenAI-compatible only.** Set for non-OpenAI hosts (OpenRouter, Groq, DeepSeek); empty means `https://api.openai.com/v1` |
| `LLM_MAX_RETRIES` | `3` | **OpenAI-compatible only.** Transient 429/5xx are common on shared free-tier pools; the SDK retries with backoff |
| `LLM_TIMEOUT_SECONDS` | `120.0` | **OpenAI-compatible only.** Per-request timeout |
| `REASONING_EFFORT` | *(empty)* | **OpenAI-compatible only.** Sent only when set. Reasoning models reject function tools on `/v1/chat/completions` unless reasoning is explicitly off, so a tool-using deployment on a reasoning model needs `none`. Note that reasoning tokens are drawn from `MAX_TOKENS` — raising effort without raising that budget produces truncated or empty replies |
| `SUMMARY_TOKEN_THRESHOLD` | `3000` | Estimated token count of unsummarized messages that triggers summarization. This is the *normal* trigger; if `MAX_UNSUMMARIZED_MESSAGES` is what keeps firing (a `WARNING` in the log), the two are inverted and this one is unreachable |
| `MAX_CHECKPOINT_MESSAGES` | `20` | Max messages kept in LangGraph's checkpoint state after a turn. Checkpoint messages are never sent to the LLM, so this only bounds Postgres row size — it is **not** context retention |
| `MAX_CONTEXT_HISTORY_MESSAGES` | `40` | Max recent (post-summary) messages fed into each turn |
| `MAX_UNSUMMARIZED_MESSAGES` | `30` | Floor that forces summarization regardless of token estimate, for a flood of very short turns. Keep it ≤ `MAX_CONTEXT_HISTORY_MESSAGES` with room to spare: at equality, a single late summarization silently drops the oldest unsummarized messages out of context |
| `MIN_RETAINED_RAW_MESSAGES` | `8` | Messages held back from summarization so the model always sees recent turns verbatim. Must be < `MAX_UNSUMMARIZED_MESSAGES`, or summarization fires with nothing left to fold and the watermark never advances |
| `MAX_SUMMARY_CHARS` | `6000` | Hard ceiling on the stored durable summary. The merge prompt is asked to stay under 75% of this; the cap only catches a model that ignored it, since a summary that grows without limit costs more context than the transcript it replaced |
| `MAX_USER_INPUT_CHARS` | `4000` | Max characters accepted in a single user message |
| `FILE_STORAGE_DIR` | `app/generated_files` | Where `LocalFileStorage` writes generated documents. Relative to the working directory, like `app/logs` — the process must be started from the repository root either way |
| `ENABLED_TOOL_PLUGINS` | *(empty)* | Comma-separated allowlist of plugin folder names under `app/plugins/`. Empty means load every plugin folder that is present |
| `TOOL_PLUGINS_STRICT` | `false` | Fail startup if any tool plugin fails to load, instead of logging and skipping it |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CONSOLE_LOG` | `false` | Also log to console |
| `CONVERSATION_LOG` | `false` | Writes the root user's turns — the user's text, the assistant's reply, and each tool call's arguments — to `app/logs/conversation_log.log`. Deliberately separate from `LOG_LEVEL`: this decides whether conversation *content* reaches disk, which is a different question from how verbose logging is. Read at import time, so changing it needs a restart |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` | `localhost` / `5432` / `llm_system` / `postgres` | PostgreSQL connection |
| `DB_PASSWORD` | *(required)* | PostgreSQL password |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | `2` / `10` | Async connection pool size (`psycopg_pool.AsyncConnectionPool`) |
| `SSE_HEARTBEAT_SECONDS` | `15` | Idle interval between `: keepalive` comments on `GET /events`, so proxies don't drop the connection |
| `SSE_QUEUE_MAXSIZE` | `256` | Per-subscriber event queue depth; a subscriber that falls this far behind is dropped rather than buffered without bound |
| `AUTH_BOOTSTRAP_USERNAME` / `AUTH_BOOTSTRAP_PASSWORD` | *(empty)* | Credentials for the single `root` user, seeded on startup. If unset and no root exists, a `root` user is created with a random password logged once at WARNING — the system is never left with no way in |
| `SESSION_TTL_HOURS` | `720` | Absolute session lifetime (30 days). No sliding expiry — that would be a write on every request |
| `SESSION_COOKIE_NAME` | `session_id` | Name of the session cookie |
| `COOKIE_SECURE` | `false` | `Secure` flag on the session cookie. Off by default because it cannot be set over plain-HTTP localhost; turn on in any real deployment |
| `COOKIE_SAMESITE` | `lax` | `SameSite` flag: `lax`, `strict`, or `none` |

The summarization prompts are part of the prompt set selected by `SYSTEM_PROMPT`: `app/prompts/<SYSTEM_PROMPT>/summary_chunk_prompt.txt` and `summary_merge_prompt.txt` are read at import time. A set is all-or-nothing — if that folder is missing or has an empty copy of `system_prompt.txt`, `summary_chunk_prompt.txt`, or `summary_merge_prompt.txt`, the loader logs a warning and falls back to `app/prompts/default/` for the entire set. The `default/` set itself must always be complete; an incomplete one raises at startup.

A set may also contain an optional `first_message.txt`. When present, its text is seeded as a complete `assistant` message when a conversation is created (resolved from the runtime persona, in the same transaction as the conversation), so the persona opens with a stated direction and the model sees that greeting as its own first turn. A set without the file simply opens with no greeting.

### Runtime settings

Most of the table above is a *default*, not a fixed value — 14 of those variables can be changed while the process is running, without a restart, and the change persists across restarts too. `DB_*`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_PROVIDER`, `FILE_STORAGE_DIR` and the other connection/provider settings cannot: they are bound into objects (a connection pool, an LLM client, a storage root) that are only built once, at startup.

| Tier | Behaviour | Examples |
|---|---|---|
| Runtime-editable, persisted | Change takes effect on the next turn; survives a restart (stored in `app_settings`) | `temperature`, `top_p`, `top_k`, `max_tokens`, `context_window`, `system_prompt_name`, `max_checkpoint_messages`, `max_context_history_messages`, `max_unsummarized_messages`, `min_retained_raw_messages`, `summary_token_threshold`, `max_summary_chars`, `sse_heartbeat_seconds`, `sse_queue_maxsize` |
| Runtime-editable, session-only | Change takes effect immediately; reverts to the environment on restart | `log_level` |
| Startup-only | Requires a restart | everything else in the table above |

In CLI mode, `/settings` lists every runtime-editable value and whether it is persisted, `/set <key> <value>` changes one, and `/reset <key>` restores its environment default. The CLI and the HTTP layer share three `Application` methods so behaviour cannot drift between the two front ends: `apply_settings()` (validate, apply, persist — the startup persisted-settings loader goes through it too), `reset_setting()` (restore one environment default and drop its `app_settings` row), and `describe_settings()` (the value / persisted / default view that both `GET /settings` and the CLI render).

### Frontend

```bash
cd ui
npm install
```

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | API origin the UI calls and opens its event stream against |

Assistant replies are rendered as Markdown. Four dependencies cover that, all confined to `Markdown.tsx` and `MermaidDiagram.tsx`:

| Package | Role |
|---|---|
| `react-markdown` | Parses Markdown into React elements. Renders to elements rather than HTML strings, so model output cannot inject markup |
| `remark-gfm` | GitHub-flavoured extensions: tables, strikethrough, task lists, autolinks |
| `rehype-highlight` | Syntax highlighting inside fenced code blocks. Configured with `detect: false`, so only fences with an explicit language tag are highlighted |
| `mermaid` | Renders a ```` ```mermaid ```` fence to SVG. Initialised with `securityLevel: "strict"`, since diagram source is untrusted model output |

The Vite dev server is pinned to port `5173` with `strictPort`, because the API's CORS allowlist names that exact origin. Without the pin, a busy port would silently move the UI to `5174` and every request — including the event stream — would fail CORS with an error that looks like the backend is down.

## Running

```bash
python -m app.main               # CLI chat
python -m app.main --api         # FastAPI server on :8000
python -m app.main --log-level DEBUG
python -m app.main --seed-admin  # reset the root user from AUTH_BOOTSTRAP_* and exit
```

CLI commands: `/exit` to quit, `/history` to print the current conversation's transcript, `/settings` to view runtime settings, `/set <key> <value>` to change one, `/reset <key>` to restore its environment default.

```bash
cd ui && npm run dev             # Vite dev server on :5173
```

The UI requires the API to be running (`python -m app.main --api`).

## Architecture

**Composition root.** [app/runtime/application.py](app/runtime/application.py) (`Application`) is an async context manager that owns the lifecycle of every shared resource. `RuntimeSettingsHolder` is built first, from the environment, before the pool even opens — `EventBus` needs it at construction time. Once the pool is open, persisted overrides are layered on top of the environment defaults. `initialize()` then applies migrations, ensures the single `root` user exists, sweeps orphaned in-flight messages left by a previous crash, loads the system prompt, builds the LLM client, opens the LangGraph PostgreSQL checkpointer, and wires the context builders, `AgentGraph`, `EventBus`, `ConversationLock`, `SummarizationService`, and `ChatService`. `app/main.py` opens one `Application` and hands it to either the CLI loop or the FastAPI app, serving the API on the same event loop the pool was opened on, and catches `KeyboardInterrupt` at the top level so a second Ctrl+C during shutdown prints a message instead of a stack trace.

**Request flow — generation is decoupled from the HTTP request.** `POST /conversations/{id}/messages` persists the user message and an empty, `status='streaming'` assistant message immediately (`ChatService.begin_turn`), then returns `202` without waiting for a response. Generation runs as a background task (`ChatService.generate`) that streams tokens from `AgentGraph`, buffers them in memory, and publishes each one to an in-process `EventBus`. Any number of clients — including the sender — read the same stream via `GET /events`, an SSE endpoint; there is exactly one token path, so multi-tab consistency falls out of the design rather than being handled as a special case. The response is written to PostgreSQL exactly once, when generation reaches a terminal state (`complete` / `cancelled` / `failed`), which is also what makes a client disconnect harmless — nothing about the turn depends on an HTTP connection staying open. A per-conversation `ConversationLock` (in-process) rejects a second concurrent send on the same conversation with `409`, since the LangGraph checkpointer is keyed by conversation and two concurrent runs would corrupt it. Summarization is scheduled afterward as a background `asyncio.Task` and never blocks or can fail the chat response.

**Shutdown.** An SSE response never ends on its own — the client stays connected and the generator keeps emitting heartbeats — so uvicorn is given `timeout_graceful_shutdown=5` to cut whatever is still open. All detached work — generation, finalization writes, summarization — is spawned through `Application.spawn` into one task registry. `Application.shutdown()` drains that registry in two passes before closing the connection pool, waiting briefly and then cancelling: the first pass cancels the in-flight generations, and cancelling one runs its `finally` block, which spawns the finalization write *into the same registry*; the second pass drains those. A cancelled generation still persists its partial answer, so the pool has to outlive both passes. Whatever does not finish in time is caught by `sweep_streaming()` on the next startup.

**Authentication** (`app/authentication/`, `app/repositories/user_repository.py`, `app/repositories/session_repository.py`). Session-based, built in-house. `POST /auth/login` verifies a username and password, inserts a `sessions` row, and returns an opaque token (`secrets.token_urlsafe(32)`) in an `HttpOnly` cookie. Only the SHA-256 hash of the token is stored, so a database dump yields no usable sessions; resolution on each request is one indexed query joined to `users` with the expiry filter baked in. Passwords are hashed with argon2id (`argon2-cffi`); the unknown-username branch of login still runs one verification so response time does not reveal whether an account exists, and both verifications run in a worker thread so they do not stall the event loop that also serves the SSE streams. Roles are `user`, `admin`, and `root`, and a partial unique index (`WHERE role = 'root'`) makes "exactly one root" a database guarantee. The root user is seeded on startup from `AUTH_BOOTSTRAP_*`, or with a random password logged once if those are unset, so the system is never left with no way in; `--seed-admin` resets the root credentials as the recovery path. `current_user` and `require_admin` are FastAPI dependencies (`app/authentication/dependencies.py`, declared with `Annotated[...]` so the `Depends` call is not a mutable default): every conversation, message, and event route requires the cookie and is scoped to the owning user — a conversation belonging to someone else returns `404`, not `403` — and `PATCH` / `DELETE /settings` require an admin. The CLI talks to `Application` directly rather than over HTTP, so it has no session; it loads the `root` user at startup and acts as it. A conversation also carries a lifecycle `status` (`active` / `held` / `closed`); `ChatService.begin_turn` refuses a non-admin send into a `held` conversation with `423`, a hook for a future admin-override feature that is otherwise inert. CSRF protection is not yet built; `SameSite=lax` already blocks the cross-site POST cookie, which is most of that surface.

**Runtime settings** (`app/config/runtime_settings.py`, `app/repositories/settings_repository.py`, `app/llm/sampling.py`). `RuntimeSettings` is a frozen dataclass; changing a value means swapping the whole instance (`RuntimeSettingsHolder.apply()`), never mutating a field, so a reader that has already taken its snapshot for the current turn cannot see a half-applied change. Consumers fall into two groups: some (`HistoryContextBuilder`, `EventBus`) hold the holder and read `.current` per use; the agent node and the checkpoint-compaction node instead take one snapshot at the top of each turn, since their settings are baked into objects built for that turn only (the model, the checkpoint limit). `FIELD_PARSERS` doubles as the allowlist — a key with no parser (`db_password`, `llm_api_key`, …) cannot be set through `apply()` by any caller, so there is no second list to keep in sync with the database or the `PATCH /settings` endpoint. Cross-field invariants (`max_tokens < context_window`, `max_unsummarized_messages ≤ max_context_history_messages`, `min_retained_raw_messages < max_unsummarized_messages`) live in `__post_init__` rather than in `apply()`, because `replace()` runs it: one implementation then covers both the runtime edit and the environment read at startup, and it raises *before* the new instance is assigned, so a rejected batch cannot leave a partially applied state behind. Persisted overrides live in the sparse `app_settings` table — one row per key that has actually been changed, so an unset key still falls through to the environment and resetting a setting is a `DELETE` rather than writing the default back; `log_level` is deliberately excluded from persistence, since it is the one lever that must still work from the environment or `--log-level` when startup itself is failing. `sampling.py` applies temperature/top_p/top_k/max_tokens/context_window to the LLM client via `.bind()` (never by rebuilding it, so a settings change cannot swap the client out from under a generation already streaming) — Ollama and OpenAI take different shapes: `ChatOllama` only reads these from its own constructor fields when assembling the request's `options` object, so they must be bound as a single nested `options={...}` dict rather than as flat kwargs, while `ChatOpenAI` accepts them as top-level kwargs directly.

**LangGraph agent** ([app/agent/graph.py](app/agent/graph.py)):

```
START → prepare_context → agent ─┬─(tool call)→ tools → agent
                                 └─(final answer)→ compact_checkpoint_state → END
```

- `prepare_context` (`app/agent/nodes/prepare_context_node.py`) runs `ConversationContextBuilder` once per request to assemble background context.
- `agent` (`app/agent/nodes/agent_node.py`) binds tools to the LLM and streams a response over `[system_prompt, prepared_context, current_turn_messages]`.
- `tools` is a LangGraph `ToolNode` over every tool the plugin loader found: `get_current_time`, and `generate_rirekisho` / `generate_shokumu_keirekisho`. `handle_tool_errors` routes a rejected call back to the model as a message naming the offending field, so a schema violation becomes a question to the user rather than a failed turn.
- `compact_checkpoint_state` (`app/agent/nodes/compact_checkpoint_state_node.py`) trims the LangGraph checkpoint history to `MAX_CHECKPOINT_MESSAGES` after a final answer, keeping checkpoint rows from growing unbounded.

State is checkpointed per conversation (`thread_id` = conversation UUID) via `AsyncPostgresSaver`.

**Tool plugins** (`app/plugins/`). The list of tools `AgentGraph` receives is never hand-assembled; `Application.initialize()` calls `load_tools()` once at startup and passes whatever it returns. A plugin is a *folder* directly under `app/plugins/` whose package exports a module-level `PLUGIN` (a `ToolPlugin`: a name, a factory function, and a description). `loader.py` walks that directory with `pkgutil.iter_modules`, considering packages only — never loose `.py` files, which is what lets `contracts.py` and `loader.py` sit beside the plugins without a skip list someone has to keep in sync — imports each one in sorted order (so the resulting tool list, which is prompt text, does not reorder itself between restarts for no reason and bust provider-side prompt caching), and calls its factory with one `ToolContext` carrying the shared dependencies a tool might need (`file_storage`, `file_repository`, `conversation_repository`). A plugin that fails to import, exports no `PLUGIN`, or whose factory raises is logged and skipped rather than taking the process down with it — `TOOL_PLUGINS_STRICT` turns that into a startup failure instead, for a deployment where a silently missing tool is worse than a failed boot. Two plugins returning a tool of the same name is never survivable, strict or not, and raises immediately: an ambiguous schema is not a condition the model can route around. `ENABLED_TOOL_PLUGINS` is an optional allowlist for running a subset. Adding a tool is: drop a folder in, restart — there is no runtime reload, because a running conversation's tool set changing mid-turn is not a case this project needs to support.

Today there are two plugins, `app/plugins/clock/` (`get_current_time`) and `app/plugins/documents/` (`generate_rirekisho` / `generate_shokumu_keirekisho`, plus the entire document-generation vertical described below). A plugin owns its whole feature — schemas, renderers, templates, one-off scripts — not just the tool wrapper; the test is that deleting a plugin's folder should remove every trace of the capability and leave nothing importing a package that no longer exists. Nothing a plugin needs but that is genuinely a fact about the application rather than about the feature — `JST`/`today_in_japan()` in `app/utils/jst.py` is the current example — lives outside the plugin instead, since a plugin is never allowed to import another plugin: two plugins needing the same helper is a signal to promote it to application core, not to reach sideways.

**Context assembly** (`app/agent/context/`):

- `SummaryContextBuilder` reads the durable summary and its watermark (`last_summarized_message_id`) — no LLM call.
- `HistoryContextBuilder` reads transcript messages after that watermark, capped at `MAX_CONTEXT_HISTORY_MESSAGES`.
- `ConversationContextBuilder` composes `[summary_messages, recent_history]` into the `prepared_context` fed to the agent node. Documented extension points: RAG retrieval and durable user-memory facts — the second is specified in [app/agent/context/TODO.md](app/agent/context/TODO.md) as structured per-document slot memory, kept separate from the prose summary because a value that is copied cannot be lost the way a value regenerated by an LLM merge can.

**Summarization** (`app/services/summarization_service.py`): after each completed turn, `ChatService` schedules `SummarizationService.trigger_if_needed`. It reads the summary state **once** and threads that snapshot through the whole run, estimates tokens (`len(text) // 4`) over messages not yet summarized and, if over `SUMMARY_TOKEN_THRESHOLD` (or `MAX_UNSUMMARIZED_MESSAGES` is exceeded), generates a chunk summary via the LLM, merges it into the existing summary via a second LLM call, and advances the watermark. No pooled connection is held across either LLM call.

Not every unsummarized message is folded. `_split_for_retention` holds back the last `MIN_RETAINED_RAW_MESSAGES`, and the watermark advances only as far as what was actually summarized, so the turn after a summarization still sees recent messages verbatim instead of a paraphrase and nothing else. Without that tail the model loses the thread at exactly the point summarization runs — re-asking questions the user has already answered and re-proposing text it has already had approved. The retained slice is extended backwards to the nearest user message so it opens with a question rather than half of an answer; if that alignment would consume the whole backlog, the unaligned split is used instead, because a watermark that never advances is the worse failure.

The merged summary is bounded twice. The merge prompt is given a length budget of 75% of `MAX_SUMMARY_CHARS` along with an explicit trim order, so the model decides *what* to lose; `_cap_summary` then truncates anything still over `MAX_SUMMARY_CHARS` and logs a warning. The prompt is for quality, the cap is the guarantee — the gap between the two is what keeps that warning meaningful rather than routine.

The write goes through `SummaryRepository.save_summary_chunk_and_advance`: the state upsert and the chunk insert commit in one transaction, and the upsert is **conditional** on the watermark still being where the caller read it (`WHERE last_summarized_message_id = %s`). A run whose watermark moved underneath it rolls back and returns `False` instead of writing a duplicate chunk. `ChatService._summarizing` is the cheap in-process guard that avoids the wasted LLM call in the common case; this check is the correctness backstop, and the only one that would survive more than one worker process. The updated summary is never written into LangGraph checkpoint state; it is read back from PostgreSQL by `SummaryContextBuilder` on the next turn.

**Document generation** (`app/plugins/documents/`, `app/storage/`, `app/repositories/file_repository.py`). Three layers, each ignorant of the ones above it. `app/plugins/documents/schemas_rirekisho.py` and `app/plugins/documents/schemas_shokumu.py` are the Pydantic contracts, one per document type — `Rirekisho` and `ShokumuKeirekisho` with their nested types — and each doubles as its tool's `args_schema`, so every field description is prompt text the model reads on each call. `schemas_shokumu` imports `YearMonth` and `KANA_PATTERN` from `schemas_rirekisho` rather than restating them: both documents carry the same person's name and the same 年月 pairs, and a rule that accepted a value on one document while rejecting it on the other would be a confusing bug to hit. A `Renderer` (`app/plugins/documents/renderers/`) knows a schema and a template and nothing else: no database, no storage, no LLM. That narrowness is what let the `.txt` renderer the schemas were developed against be swapped for `XlsxRenderer` and `DocxRenderer` by changing one argument each in `tools.py`. A `FileStorage` (`app/storage/`) holds bytes; `LocalFileStorage` is the development backend, writing to `FILE_STORAGE_DIR` under date-prefixed keys (`2026/09/04/<uuid>.xlsx`) that map directly onto S3 object keys later. The storage layer generates its own keys and a caller cannot supply one, so a model-supplied filename can never reach a filesystem path — path traversal is impossible by construction rather than by validation. Writes go to a temporary name and are renamed into place, so a crash mid-write leaves a stray `.part` file rather than a truncated document that looks complete.

`generate_rirekisho` and `generate_shokumu_keirekisho` (`app/plugins/documents/tools.py`) are built by one closure factory with those dependencies bound in, for the same reason as `make_current_user`: reaching for module globals would make the graph impossible to construct twice. `app/plugins/documents/__init__.py` is the thin layer that exposes this factory to the plugin loader as a `PLUGIN` — the vertical's only concession to being a plugin at all. Every document type validates, renders, stores and records its file the same way — only the schema, template and `document_type` differ — so that body was factored into a single builder once a second document made the duplication real rather than hypothetical. Each tool re-validates its arguments through its schema even though LangChain already checked them against `args_schema` — that second pass is what turns a dict back into a typed object, and the only guarantee that what gets rendered is what passed validation. Identity comes from the run configuration (`thread_id`, `assistant_message_id`), never from the tool arguments, since a conversation id supplied by the model could name someone else's conversation. Bytes are written before the row, because the reverse order can produce a row pointing at a file that does not exist — which the user meets as a failed download — while this order can only leave an unreferenced blob. The string returned to the model is terse and forbids it from writing a link of its own: told only that a file "is attached", a model will construct a plausible download path around the filename, and an early test run produced `sandbox:/mnt/data/…`, a convention from its training data that points nowhere here. The real download comes from the message attachment, so any link the model writes is broken by construction.

**Filling the 履歴書 form** (`app/plugins/documents/renderers/xlsx_renderer.py`, `app/plugins/documents/layouts/rirekisho_jis.py`, `app/plugins/documents/renderers/ooxml.py`). The form is filled, never built: its ruling, 96 merged ranges, column widths, print setup and 写真を貼る位置 box come from a template workbook a person made in Excel, and the renderer only writes text into cells that already exist. `layouts/rirekisho_jis.py` is the cell map, transcribed from the real file rather than computed — the ruling is irregular (`D28:I29` spans two rows, `D34:I34` spans one), so an anchor list is the only description that is actually true of it. openpyxl reproduces cells, styles, merges and page setup exactly but does not model DrawingML shapes, so saving silently drops the photo box; `ooxml.restore_drawings` copies that part back into the saved package, along with the worksheet relationship, the `<drawing>` element and the content-type override that a valid package needs. `app/plugins/documents/scripts/make_rirekisho_template.py` builds the blank template from the approved sample by clearing exactly the cells the applicant filled — a plugin-local script, run by hand, not part of the loaded application.

Capacity is the interesting constraint. A printed 履歴書 has as many ruled lines as it has, so the layout module measures text in the half-width units Excel uses for column width and applies two caps: text that overflows a region steps the font down, and text that still overflows at the smallest readable size raises `LayoutOverflow`. Shrinking silently is fine — the reader sees smaller text. Truncating silently is not, because this document goes to an employer and a half-printed company name is worse than a generation that failed and asked a question. `LayoutOverflow` and the row-count checks are written in Japanese and phrased as guidance, because they reach the assistant through `ToolNode`'s error handler and become the question it asks the user ("this is more rows than the form holds — shall we merge the 入社 and 退職 lines?").

**Filling the 職務経歴書** (`app/plugins/documents/renderers/docx_renderer.py`). None of that applies here: a `.docx` flows and paginates itself, so there is no slot map, no capacity budget and no overflow to raise. The renderer instead flattens each section into a list of lines and hands them to a docxtpl template that loops over them with a single tag. All the branching that decides what a section says therefore lives in Python, where it can be read and tested, rather than as three template paragraphs per optional field — which is also why an empty section renders as nothing at all instead of a heading over an empty table. `app/plugins/documents/scripts/make_shokumu_template.py` builds that template from the approved sample, keeping its page size, margins, footers, MS 明朝 at 10pt and table ruling, and replacing the sample's text with tags.

The four approved 職務経歴書 references disagree with each other — on whether they carry ■PCスキル or ■資格, on how many 自己PR blocks they argue, on whether the job table has side columns. Every difference is a *presence* difference rather than a structural one, so the schema holds the union and the template renders one shape whose sections appear only when populated.

Validators enforce *format*, never completeness: every one returns early on an empty value, because a blank field means the user chose not to supply it, and a 履歴書 printed with blanks is a normal way to use the form. Only a value that is present and malformed is an error. Furigana is the case where that distinction has teeth — `name_kana` is kana-only, but `address_kana` also accepts digits and hyphens, since Japanese address furigana carries block numbers as numerals (`しんじゅく3-12-8`) rather than transcribing them phonetically. Applying the name rule to the address rejected correct input and pushed users into dropping real information to satisfy the validator.

Dates are stored as 西暦 and converted only when rendered. The application-wide fact — `JST`, `today_in_japan()` — lives in `app/utils/jst.py`, since the clock plugin needs it too and a plugin may never import another plugin's internals; the document-specific formatting — `to_japanese_era`, `to_japanese_era_year`, `age_on` — stays in `app/plugins/documents/dates.py`. Chronological ordering and the birth-date check both need a monotonic year, and 平成/令和 are a presentation of that year rather than a different fact — so nothing upstream of a template knows about eras. Age is derived the same way, from `birth_date` and the document's own date, which is why it is not a schema field: it is a fact about the rendered document, not about the applicant, and a field would invite the model to invent one. The 和暦 helpers currently have no caller — the chosen 履歴書 layout prints 西暦, as both of the client-approved samples using that form do — and are kept for the alternative layout that does. A `HistoryEntry` may also omit its `period` entirely, for the final ongoing row a 履歴書 writes as 現在に至る; the validator allows that only as the last row, since a dateless entry means "still true" and cannot precede one that ended.

**Persistence** — two separate stores:
- Application data (PostgreSQL, `app/database/`, `app/repositories/`): `users`, `sessions` (opaque session tokens, stored as SHA-256 hashes), `conversations` (each owned by a user, with a lifecycle `status`), `messages`, `conversation_summary_state` (current summary + watermark), `conversation_summaries` (historical chunk log), `generated_files` (document metadata and its storage key, cascading from conversation, message and user; the bytes themselves live in `FileStorage`, not in the database), `app_settings` (sparse key/value store of persisted runtime-setting overrides). Tables are created on startup if missing; `app/database/migrations.py` applies versioned schema changes to tables that already exist (tracked in `schema_migrations`), since `CREATE TABLE IF NOT EXISTS` cannot. Every repository (`app/repositories/`) is async and reads/writes through one shared `psycopg_pool.AsyncConnectionPool`, returning typed dataclasses (`psycopg.rows.class_row`) rather than positional tuples.
- LangGraph checkpoint state: managed separately by `AsyncPostgresSaver` (`app/agent/checkpointer.py`) for graph replay/resumption. It opens its own connection independent of the application pool.

**Realtime** (`app/runtime/event_bus.py`, `app/runtime/conversation_lock.py`):
- `EventBus` is in-process pub/sub, keyed by conversation. `publish()` is synchronous and never blocks, so a slow subscriber cannot stall generation; each subscriber holds a bounded `asyncio.Queue` (`SSE_QUEUE_MAXSIZE`) and is dropped rather than buffered without limit if it falls behind. Event types: `message.created`, `message.delta`, `message.completed`, `message.cancelled`, `message.failed`, `conversation.updated`.
- `ConversationLock` is an in-process `dict`-backed lock serializing generation per conversation. Correct without a `Lock`/mutex only because acquisition never awaits between the membership check and the insert.
- Both are process-local. A multi-worker deployment would need `LISTEN/NOTIFY` (event bus) and a PostgreSQL advisory lock (conversation lock) instead — the interfaces are kept narrow enough that this is a swap, not a rewrite.

**Logging** (`app/utils/logger.py`, `app/utils/conversation_log.py`). One named logger (`llm_app`) writing a daily rotating file under `app/logs/`, optionally mirrored to the console. Third-party libraries log to their own loggers and never propagate into it, so `LOG_LEVEL=DEBUG` yields this project's own tracing rather than a firehose.

`CONVERSATION_LOG=true` attaches a second handler writing `app/logs/conversation_log.log`: the turn-by-turn transcript, each tool call's arguments as indented JSON (`ensure_ascii=False`, so Japanese is readable rather than escaped), and the graph's node transitions — enough to see exactly what the model received and what it passed to a tool. Two filters keep the two files apart and both are necessary. `_RootConversationFilter` admits only the root user's turns, and only from the four modules that describe a turn, matched on `LogRecord.module` because every module shares the one logger. `ExcludeConversationContent` does the opposite job on the daily log and the console: without it, `LOG_LEVEL=DEBUG` would copy every name, address and phone number the user typed into a second file whose handling nobody reasoned about.

The acting user reaches those filters through a `ContextVar` set in `ChatService.begin_turn`. asyncio copies the current context into every task it creates, and `begin_turn` is awaited rather than spawned, so the value lands in the caller's context and is inherited by the spawned generation task, the graph run inside it, and each tool call — without threading a parameter through any of them, in either the CLI or the API. The logger itself sits at `DEBUG` whenever conversation logging is on, purely so those records can reach that handler; every other handler carries `LOG_LEVEL` as its own level, which is also why `set_log_level` applies a runtime change per handler instead of to the logger — lifting the logger would silently switch the conversation log off.

**Frontend** (`ui/src/`): React 19 + TypeScript on Vite, with TanStack Query used only as a cache for the two REST resources — it is deliberately absent from the streaming path.

The selected conversation lives in the URL (`/c/:conversationId`), so a refresh, a bookmark and a second tab all resolve to the same conversation. `ChatPage` reads that route parameter and wires four hooks, all keyed by it:

- `useConversations` — the sidebar list, plus creation and cache invalidation. Also exports `useConversationsRefresh`, the seam that lets the event stream mark the list stale without importing a cache library.
- `useMessages` — the persisted transcript, plus `useMessageCache` giving the stream write access to it. No writer ever invents a row: an event about a message that is not cached triggers a refetch instead.
- `useConversationStream` — one `EventSource` per conversation, tied to the conversation rather than to sending, because the server treats the sender as an ordinary subscriber. Tokens accumulate in a ref and are published to React state once per animation frame, so rendering is decoupled from the model's output rate. Its state carries the conversation id it belongs to, which makes a conversation switch a comparison during render rather than a reset effect.
- `useChat` — sends a turn and reports why one was refused. It owns no message state: the user's own message arrives back over the event stream like everyone else's, so there is one rendering path rather than two.

`Chat.tsx` renders each message as `drafts[id] ?? message.content` — while a turn is in flight the database row is still empty and the text exists only on the wire; the terminal event writes the authoritative content and drops the draft, so the fallback resolves itself. Below the text it renders `message.attachments` as download links to `GET /files/{id}`. A message announced by `message.created` cannot have files yet, so the stream inserts it with an empty list rather than guessing; attachments arrive with the persisted row.

Assistant messages are rendered through `Markdown.tsx`; user messages are not, so a user typing literal `**` sees it unchanged. A ```` ```mermaid ```` fence is diverted to `MermaidDiagram.tsx` and drawn as SVG. Because content streams in token by token, a fence is incomplete for most of an answer, and a half-typed diagram never parses — so `Chat.tsx` passes an `isStreaming` flag down and mermaid is not called at all until the message finishes. When it is called, `mermaid.parse({ suppressErrors: true })` validates first: it is `render()` on invalid input that leaves orphaned error graphics in `<body>`, which accumulate faster than they can be cleaned up and only a full page reload clears. Unclosed Markdown resolves itself once the closing marker arrives.

Recovery is deliberately simple. Deltas are not replayable, so the stream re-reads the transcript on every connect and reconnect, and a client that joins mid-generation renders partial text until the terminal event delivers the full content. That is the entire answer to a dropped connection — no `Last-Event-ID`, no server-side replay buffer.

`App.tsx` also routes `/setting` to `SettingPage.tsx`, currently an empty placeholder reserved for a UI over the runtime settings described above.

Authentication is a gate around the whole app rather than a route. `AuthProvider` (`ui/src/auth/`) holds one TanStack Query entry for `GET /auth/me` whose query function swallows a `401` into `null`, so "not logged in" is data rather than an error; `AuthGate` renders `LoginPage` or the app from it. A session that expires mid-use is caught in one place: the provider subscribes to the query and mutation caches and flips the auth entry to `null` on any `401`, so every screen reacts to a lost session without a single component checking for it. Signing out clears every cached query except the auth entry itself, so the next user never sees the previous one's conversations. `api/client.ts` sends `credentials: "include"` on every `fetch` and `useConversationStream` opens its `EventSource` with `withCredentials: true`, which is what carries the `HttpOnly` cookie onto the event stream.

The context is split across two files on purpose — `AuthContext.ts` exports the hook and context, `AuthProvider.tsx` exports only the component — because a module exporting both a component and non-components defeats React Fast Refresh, which ESLint's `react-refresh/only-export-components` rule enforces.

**LLM** (`app/llm/`). `llm_factory.py` holds a provider registry and returns a LangChain `BaseChatModel`, so the rest of the codebase never names a vendor. `ollama_llm.py` builds `ChatOllama`; `openai_llm.py` builds `ChatOpenAI` and accepts a custom `base_url`, which covers OpenRouter, Groq, DeepSeek and anything else speaking the OpenAI Chat Completions API. An unknown `LLM_PROVIDER` fails at startup with the list of valid values. `system_prompt.py` loads the persona from the prompt set named by `SYSTEM_PROMPT` (`app/prompts/<name>/system_prompt.txt`); set resolution lives in `config/prompts.py` and is all-or-nothing, so an incomplete folder falls back — persona included — to the `default/` set, and an unreadable `default/` degrades to a built-in prompt rather than failing startup. Every persona, including that fallback, is composed with a shared `RESPONSE_FORMAT` block describing what the frontend can render (Markdown, mermaid, no LaTeX or raw HTML). That contract belongs to the interface rather than to any one persona, so it lives in code instead of being duplicated across prompt files. The composed prompt is measured against `SYSTEM_PROMPT_TOKEN_BUDGET` and logs a warning when it exceeds it — a warning rather than an error, because a long prompt still works and this module's contract is to degrade rather than block startup.

## API (`--api` mode)

Every route except `POST /auth/login` requires the session cookie. Conversation, message, and event routes are scoped to the authenticated user; a conversation owned by someone else is reported as `404`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/login` | Body: `{"username": str, "password": str}`. On success, sets the `HttpOnly` session cookie and returns `{id, username, role}`; `401` on bad credentials |
| `POST` | `/auth/logout` | Deletes the current session and clears the cookie. `204` |
| `GET` | `/auth/me` | The current user as `{id, username, role}`, or `401` |
| `POST` | `/conversations` | Create a conversation owned by the caller |
| `GET` | `/conversations` | List the caller's conversations (each includes a lifecycle `status`: `active` / `held` / `closed`) |
| `GET` | `/conversations/{id}/messages` | Get a conversation's transcript (includes `status` per message: `streaming` / `complete` / `interrupted` / `cancelled` / `failed`) |
| `POST` | `/conversations/{id}/messages` | Open a turn and start generating in the background. Body: `{"client_message_id": UUID, "message": str}`. Returns `202` with `{user_message_id, assistant_message_id}` immediately — the response is not in this call, only over `GET /events`. `client_message_id` is an idempotency key: a retried send with the same key returns the original ids (`200`) rather than generating a second answer. A second concurrent send on the same conversation while one is in flight gets `409` with the in-flight `assistant_message_id`, so the caller can subscribe to it instead. A send into a conversation an admin has put on hold gets `423` |
| `GET` | `/events?conversation_id={id}` | Server-sent events (`text/event-stream`) for one conversation. Any number of clients may subscribe and all receive the same stream, which is what keeps multiple tabs on the same conversation consistent |
| `GET` | `/files/{file_id}` | Download a generated document as an attachment. Scoped to the owning user (admins may read any); someone else's file is reported as `404`, not `403`, so an id they cannot see is never confirmed to exist. A row whose bytes are missing is logged at `ERROR` — that is our inconsistency, not a bad request — but still answered `404` |
| `GET` | `/settings` | Every runtime-adjustable setting with its live value, whether it persists, and its environment default |
| `PATCH` | `/settings` | Apply a batch of setting changes (`{key: value}`). **Admin only.** `422` on an unknown key or invalid value |
| `DELETE` | `/settings/{key}` | Reset one setting to its environment default, dropping any persisted override. **Admin only** |

CORS is restricted to `http://localhost:5173` (the Vite dev server for `ui/`), with `allow_credentials=True` so the browser sends the session cookie.

## Folder Structure

```
llm-system/
├── app/                                          # Main LLM Related Files
│   ├── main.py                                   # Main entry point (CLI, --api, or --seed-admin)
│   ├── agent/                                    # LangGraph orchestrator
│   │   ├── nodes/
│   │   │   ├── prepare_context_node.py           # Builds prepared_context once per request
│   │   │   ├── agent_node.py                     # LLM decision node (binds tools, streams the model)
│   │   │   └── compact_checkpoint_state_node.py  # Bounds checkpoint history after a final answer
│   │   ├── context/
│   │   │   ├── conversation_context_builder.py   # Composes summary + history context for one request
│   │   │   ├── summary_context_builder.py        # Reads the durable summary and its watermark (no LLM)
│   │   │   ├── history_context_builder.py        # Reads transcript messages after the summary watermark
│   │   │   └── TODO.md                           # Planned: structured slot memory, RAG context
│   │   ├── checkpointer.py                       # Creates the AsyncPostgresSaver checkpoint context
│   │   ├── graph.py                              # Defines and compiles the LangGraph (streams LLM tokens)
│   │   └── state.py                              # Defines LangGraph state (AgentState)
│   ├── authentication/                           # Session-based auth (login, sessions, roles)
│   │   ├── auth_service.py                       # login / logout / resolve a session token to a User
│   │   ├── authorization.py                      # Role constants + is_admin() / can()
│   │   ├── dependencies.py                       # FastAPI current_user / require_admin dependencies
│   │   ├── models.py                             # User dataclass
│   │   ├── passwords.py                          # argon2id hashing + timing-safe dummy verify
│   │   ├── seed.py                               # Ensure the single root user exists (startup + --seed-admin)
│   │   └── tokens.py                             # Opaque session token generation and SHA-256 hashing
│   ├── config/
│   │   ├── settings.py                           # Load env values, other constant variables
│   │   ├── prompts.py                            # Resolve the prompt set folder for SYSTEM_PROMPT, all-or-nothing fallback to default/
│   │   └── runtime_settings.py                   # RuntimeSettings (frozen dataclass) + RuntimeSettingsHolder
│   ├── database/
│   │   ├── connection.py                         # Sync connection (schema setup only) + the shared async pool
│   │   ├── init_db.py                            # Create database/tables if missing, then run migrations
│   │   └── migrations.py                         # Versioned schema changes to tables that already exist
│   ├── plugins/                                  # Tool plugins: discovered and loaded once at startup
│   │   ├── contracts.py                          # ToolContext, ToolPlugin — the contract every plugin is built against
│   │   ├── loader.py                             # Discovers plugin folders, calls each factory, enforces unique tool names + token budget
│   │   ├── clock/
│   │   │   ├── __init__.py                       # PLUGIN — exposes get_current_time
│   │   │   └── tools.py
│   │   └── documents/                            # The whole 履歴書/職務経歴書 vertical, as one self-contained plugin
│   │       ├── __init__.py                       # PLUGIN — exposes generate_rirekisho / generate_shokumu_keirekisho
│   │       ├── tools.py                          # The two tools; one shared builder (validate, render, store, record)
│   │       ├── schemas_rirekisho.py              # Pydantic Rirekisho schema; doubles as the tool's args_schema
│   │       ├── schemas_shokumu.py                # Pydantic ShokumuKeirekisho schema; shares YearMonth / KANA_PATTERN / LicenseEntry
│   │       ├── dates.py                          # 西暦→和暦 conversion, 満年齢 — document-specific date formatting only
│   │       ├── layouts/
│   │       │   └── rirekisho_jis.py              # Cell map + capacity model for the JIS 履歴書 form; LayoutOverflow
│   │       ├── renderers/
│   │       │   ├── base.py                       # Renderer protocol (extension, content_type, render)
│   │       │   ├── xlsx_renderer.py               # Fills the 履歴書 form: writes cells, shrinks fonts, raises on overflow
│   │       │   ├── docx_renderer.py               # Fills the 職務経歴書 template via docxtpl; flattens sections to lines
│   │       │   └── ooxml.py                       # Restores the photo-box drawing openpyxl drops when it saves
│   │       ├── templates/
│   │       │   ├── rirekisho.xlsx                # Blank JIS 履歴書 form (ruling, print setup, 写真を貼る位置 box)
│   │       │   └── shokumu_keirekisho.docx        # 職務経歴書 template with docxtpl tags (MS 明朝 10pt, ruled tables)
│   │       └── scripts/                          # One-off developer tools, run by hand and checked in Word/Excel
│   │           ├── make_rirekisho_template.py    # Blanks the approved 履歴書 sample into templates/
│   │           └── make_shokumu_template.py      # Turns the approved 職務経歴書 sample into a docxtpl template
│   ├── storage/                                  # Where generated file bytes live
│   │   ├── base.py                               # FileStorage protocol; storage generates its own keys
│   │   └── local_storage.py                      # Local disk backend; date-prefixed keys, atomic rename
│   ├── generated_files/                          # Default FILE_STORAGE_DIR target (gitignored)
│   ├── llm/                                      # Model provider selection, isolated from the rest of the app
│   │   ├── llm_factory.py                        # Provider registry; returns a LangChain BaseChatModel
│   │   ├── ollama_llm.py                         # Builds ChatOllama (local models)
│   │   ├── openai_llm.py                         # Builds ChatOpenAI; custom base_url covers OpenRouter/Groq/DeepSeek
│   │   ├── sampling.py                           # Binds runtime sampling params onto the LLM client per provider
│   │   └── system_prompt.py                      # Loads the persona from the SYSTEM_PROMPT set, with fallback
│   ├── logs/                                     # Daily log files + conversation_log.log (gitignored)
│   ├── prompts/                                  # One folder per prompt set; SYSTEM_PROMPT picks one
│   │   ├── default/                              # Fallback set — must always be complete
│   │   │   ├── system_prompt.txt                 # Generic fallback persona
│   │   │   ├── summary_chunk_prompt.txt          # Prompt for summarizing one batch of new messages
│   │   │   └── summary_merge_prompt.txt          # Prompt for merging a chunk summary into the durable summary
│   │   ├── anna/                                 # Japanese career-support persona (履歴書 / 職務経歴書 interviewing)
│   │   │   ├── system_prompt.txt
│   │   │   ├── first_message.txt                 # Optional: assistant's opening message, seeded at conversation creation
│   │   │   ├── summary_chunk_prompt.txt
│   │   │   └── summary_merge_prompt.txt
│   │   └── debug/                                # Diagnostic persona: reports what context actually reached the model
│   │       ├── system_prompt.txt
│   │       ├── summary_chunk_prompt.txt
│   │       └── summary_merge_prompt.txt
│   ├── repositories/                             # Functions for executing SQL against tables.
│   │   ├── conversation_repository.py            # Conversation CRUD + lifecycle status; owned by a user
│   │   ├── file_repository.py                    # generated_files rows: document metadata + storage key
│   │   ├── message_repository.py                 # Transcript rows: opens a turn (both messages), source of truth for history
│   │   ├── session_repository.py                 # Session rows: hashed token -> user, with expiry
│   │   ├── settings_repository.py                # Persisted overrides for runtime-adjustable settings (app_settings)
│   │   ├── summary_repository.py                 # Durable summary state + summary chunk history per conversation
│   │   └── user_repository.py                    # Users, roles, and the single root
│   ├── runtime/
│   │   ├── application.py                        # Initializes entire app. Composition root and lifecycle owner.
│   │   ├── cli.py                                # CLI interface for app.
│   │   ├── server.py                             # FastAPI REST API for app.
│   │   ├── event_bus.py                          # In-process pub/sub fan-out of conversation events (SSE source)
│   │   └── conversation_lock.py                  # Serializes generation per conversation
│   ├── services/
│   │   ├── chat_service.py                       # Opens turns, runs background generation, schedules summarization
│   │   └── summarization_service.py              # Generates and persists durable conversation summaries (LLM calls)
│   └── utils/
│       ├── logger.py                             # Logging setup; per-handler levels
│       ├── conversation_log.py                   # Root-only conversation transcript log + its two filters
│       └── jst.py                                # JST, today_in_japan() — shared across plugins, owned by none
├── ui/                                           # React + TypeScript frontend (Vite)
│   ├── index.html
│   ├── vite.config.ts                            # Dev server pinned to :5173 to match the API's CORS origin
│   ├── package.json
│   └── src/
│       ├── main.tsx                              # Root render; QueryClientProvider + BrowserRouter
│       ├── App.tsx                               # Routes; /c/:conversationId carries the selected conversation
│       ├── api/
│       │   ├── client.ts                         # fetch wrapper, ApiError, endpoint functions, event stream URL
│       │   └── types.ts                          # Message/Conversation shapes + SSE envelope and payload types
│       ├── auth/
│       │   ├── AuthContext.ts                    # Auth context + useAuth hook (no components, for Fast Refresh)
│       │   ├── AuthProvider.tsx                  # Owns the /auth/me query, login/logout, and the 401 chokepoint
│       │   └── AuthGate.tsx                      # Renders LoginPage or the app depending on auth state
│       ├── hooks/
│       │   ├── useConversations.ts               # Sidebar list, creation, and cache invalidation for the stream
│       │   ├── useMessages.ts                    # Transcript query + write access to its cache
│       │   ├── useConversationStream.ts          # One EventSource per conversation; owns the live token drafts
│       │   ├── useChat.ts                        # Opens a turn (POST); owns no message state
│       │   └── useTheme.ts                       # Light/dark theme
│       ├── layout/
│       │   ├── ChatPage.tsx                      # Reads the route param and wires the four hooks together
│       │   ├── LoginPage.tsx                     # Username/password form; the only screen shown when signed out
│       │   └── SettingPage.tsx                   # Placeholder — reserved for a UI over runtime settings
│       ├── components/
│       │   ├── Chat.tsx                          # Renders persisted messages merged with live drafts
│       │   ├── Markdown.tsx                      # Renders assistant text as Markdown; routes mermaid fences
│       │   ├── MermaidDiagram.tsx                # Renders one mermaid fence to SVG
│       │   ├── Sidebar.tsx                       # Conversation list, active highlight, new chat
│       │   ├── Navbar.tsx
│       │   └── Footer.tsx
│       └── assets/
│           ├── css/                              # style.css, chat.css, sidebar.css
│           └── images/
├── documentation/                                # Reference material, including the client-approved samples
│   └── other/                                    # Real 履歴書 (.xlsx) and 職務経歴書 (.docx) the layouts were built from
├── deploy/                                       # Deployment artifacts (nothing built yet)
│   └── TODO.md                                   # Tasks for containerizing backend + frontend; likely home for CI/CD config
├── LICENSE
├── THIRD-PARTY-NOTICES
├── README.md
└── requirements.txt
```
