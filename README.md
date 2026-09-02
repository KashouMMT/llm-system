# llm-system

A conversational LLM system built on LangChain and LangGraph, with PostgreSQL-backed persistence and rolling summarization for long-running conversations. The model provider is selectable at startup (`LLM_PROVIDER`): a local Ollama instance, or any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq, DeepSeek). Runs as a CLI or a FastAPI server, with a React + TypeScript frontend in `ui/` that receives tokens over Server-Sent Events.

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
| `SYSTEM_PROMPT` | `default` | Filename (without `.txt`) under `app/prompts/`; falls back to a built-in prompt if the file is missing or empty |
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
| `SUMMARY_TOKEN_THRESHOLD` | `1200` | Estimated token count of unsummarized messages that triggers summarization |
| `MAX_CHECKPOINT_MESSAGES` | `20` | Max messages kept in LangGraph's checkpoint state after a turn. Checkpoint messages are never sent to the LLM, so this only bounds Postgres row size |
| `MAX_CONTEXT_HISTORY_MESSAGES` | `12` | Max recent (post-summary) messages fed into each turn |
| `MAX_UNSUMMARIZED_MESSAGES` | `12` | Hard cap that forces summarization regardless of token estimate. Keep it ≤ `MAX_CONTEXT_HISTORY_MESSAGES`, otherwise the backlog can outgrow the history window and older unsummarized messages become invisible to the model |
| `MAX_USER_INPUT_CHARS` | `4000` | Max characters accepted in a single user message |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CONSOLE_LOG` | `false` | Also log to console |
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

The summarization prompts are not environment-configurable: `app/prompts/default_summary_chunk_prompt.txt` and `app/prompts/default_summary_merge_prompt.txt` are read at import time and must exist and be non-empty.

### Runtime settings

Most of the table above is a *default*, not a fixed value — 12 of those variables can be changed while the process is running, without a restart, and the change persists across restarts too. `DB_*`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_PROVIDER` and the other connection/provider settings cannot: they are bound into objects (a connection pool, an LLM client) that are only built once, at startup.

| Tier | Behaviour | Examples |
|---|---|---|
| Runtime-editable, persisted | Change takes effect on the next turn; survives a restart (stored in `app_settings`) | `temperature`, `top_p`, `top_k`, `max_tokens`, `context_window`, `system_prompt_name`, `max_checkpoint_messages`, `max_context_history_messages`, `max_unsummarized_messages`, `summary_token_threshold`, `sse_heartbeat_seconds`, `sse_queue_maxsize` |
| Runtime-editable, session-only | Change takes effect immediately; reverts to the environment on restart | `log_level` |
| Startup-only | Requires a restart | everything else in the table above |

In CLI mode, `/settings` lists every runtime-editable value and whether it is persisted, `/set <key> <value>` changes one, and `/reset <key>` restores its environment default. `Application.apply_settings()` is the single entry point the CLI, the `PATCH /settings` HTTP endpoint, and the startup persisted-settings loader all call — validation, application, and persistence happen in one place regardless of caller.

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

**Shutdown.** An SSE response never ends on its own — the client stays connected and the generator keeps emitting heartbeats — so uvicorn is given `timeout_graceful_shutdown=5` to cut whatever is still open. `Application.shutdown()` then drains detached work in two passes before closing the connection pool, waiting briefly and then cancelling: first the generation tasks, then `ChatService`'s own tasks. The order matters, because cancelling a generation is what *creates* its finalization task, and that task still needs the pool to persist the partial answer. Whatever does not finish in time is caught by `sweep_streaming()` on the next startup.

**Authentication** (`app/authentication/`, `app/repositories/user_repository.py`, `app/repositories/session_repository.py`). Session-based, built in-house. `POST /auth/login` verifies a username and password, inserts a `sessions` row, and returns an opaque token (`secrets.token_urlsafe(32)`) in an `HttpOnly` cookie. Only the SHA-256 hash of the token is stored, so a database dump yields no usable sessions; resolution on each request is one indexed query joined to `users` with the expiry filter baked in. Passwords are hashed with argon2id (`argon2-cffi`); the unknown-username branch of login still runs one verification so response time does not reveal whether an account exists, and both verifications run in a worker thread so they do not stall the event loop that also serves the SSE streams. Roles are `user`, `admin`, and `root`, and a partial unique index (`WHERE role = 'root'`) makes "exactly one root" a database guarantee. The root user is seeded on startup from `AUTH_BOOTSTRAP_*`, or with a random password logged once if those are unset, so the system is never left with no way in; `--seed-admin` resets the root credentials as the recovery path. `current_user` and `require_admin` are FastAPI dependencies (`app/authentication/dependencies.py`, declared with `Annotated[...]` so the `Depends` call is not a mutable default): every conversation, message, and event route requires the cookie and is scoped to the owning user — a conversation belonging to someone else returns `404`, not `403` — and `PATCH` / `DELETE /settings` require an admin. The CLI talks to `Application` directly rather than over HTTP, so it has no session; it loads the `root` user at startup and acts as it. A conversation also carries a lifecycle `status` (`active` / `held` / `closed`); `ChatService.begin_turn` refuses a non-admin send into a `held` conversation with `423`, a hook for a future admin-override feature that is otherwise inert. CSRF protection and the browser SPA's login flow are not yet built.

**Runtime settings** (`app/config/runtime_settings.py`, `app/repositories/settings_repository.py`, `app/llm/sampling.py`). `RuntimeSettings` is a frozen dataclass; changing a value means swapping the whole instance (`RuntimeSettingsHolder.apply()`), never mutating a field, so a reader that has already taken its snapshot for the current turn cannot see a half-applied change. Consumers fall into two groups: some (`HistoryContextBuilder`, `EventBus`) hold the holder and read `.current` per use; the agent node and the checkpoint-compaction node instead take one snapshot at the top of each turn, since their settings are baked into objects built for that turn only (the model, the checkpoint limit). `FIELD_PARSERS` doubles as the allowlist — a key with no parser (`db_password`, `llm_api_key`, …) cannot be set through `apply()` by any caller, so there is no second list to keep in sync with the database or the `PATCH /settings` endpoint. Persisted overrides live in the sparse `app_settings` table — one row per key that has actually been changed, so an unset key still falls through to the environment and resetting a setting is a `DELETE` rather than writing the default back; `log_level` is deliberately excluded from persistence, since it is the one lever that must still work from the environment or `--log-level` when startup itself is failing. `sampling.py` applies temperature/top_p/top_k/max_tokens/context_window to the LLM client via `.bind()` (never by rebuilding it, so a settings change cannot swap the client out from under a generation already streaming) — Ollama and OpenAI take different shapes: `ChatOllama` only reads these from its own constructor fields when assembling the request's `options` object, so they must be bound as a single nested `options={...}` dict rather than as flat kwargs, while `ChatOpenAI` accepts them as top-level kwargs directly.

**LangGraph agent** ([app/agent/graph.py](app/agent/graph.py)):

```
START → prepare_context → agent ─┬─(tool call)→ tools → agent
                                 └─(final answer)→ compact_checkpoint_state → END
```

- `prepare_context` (`app/agent/nodes/prepare_context_node.py`) runs `ConversationContextBuilder` once per request to assemble background context.
- `agent` (`app/agent/nodes/agent_node.py`) binds tools to the LLM and streams a response over `[system_prompt, prepared_context, current_turn_messages]`.
- `tools` is a LangGraph `ToolNode` over `app/agent/tools/` (currently just `get_current_time`).
- `compact_checkpoint_state` (`app/agent/nodes/compact_checkpoint_state_node.py`) trims the LangGraph checkpoint history to `MAX_CHECKPOINT_MESSAGES` after a final answer, keeping checkpoint rows from growing unbounded.

State is checkpointed per conversation (`thread_id` = conversation UUID) via `AsyncPostgresSaver`.

**Context assembly** (`app/agent/context/`):

- `SummaryContextBuilder` reads the durable summary and its watermark (`last_summarized_message_id`) — no LLM call.
- `HistoryContextBuilder` reads transcript messages after that watermark, capped at `MAX_CONTEXT_HISTORY_MESSAGES`.
- `ConversationContextBuilder` composes `[summary_messages, recent_history]` into the `prepared_context` fed to the agent node. Documented extension points: RAG retrieval and durable user-memory facts.

**Summarization** (`app/services/summarization_service.py`): after each turn, `ChatService` schedules `SummarizationService.trigger_if_needed`, which estimates tokens (`len(text) // 4`) over messages not yet summarized and, if over `SUMMARY_TOKEN_THRESHOLD` (or `MAX_UNSUMMARIZED_MESSAGES` is exceeded), generates a chunk summary via the LLM, merges it into the existing summary via a second LLM call, and advances the watermark — all through `SummaryRepository` (chunk insert + state update commit in one transaction). The updated summary is never written into LangGraph checkpoint state; it is read back from PostgreSQL by `SummaryContextBuilder` on the next turn.

**Persistence** — two separate stores:
- Application data (PostgreSQL, `app/database/`, `app/repositories/`): `users`, `sessions` (opaque session tokens, stored as SHA-256 hashes), `conversations` (each owned by a user, with a lifecycle `status`), `messages`, `conversation_summary_state` (current summary + watermark), `conversation_summaries` (historical chunk log), `app_settings` (sparse key/value store of persisted runtime-setting overrides). Tables are created on startup if missing; `app/database/migrations.py` applies versioned schema changes to tables that already exist (tracked in `schema_migrations`), since `CREATE TABLE IF NOT EXISTS` cannot. Every repository (`app/repositories/`) is async and reads/writes through one shared `psycopg_pool.AsyncConnectionPool`, returning typed dataclasses (`psycopg.rows.class_row`) rather than positional tuples.
- LangGraph checkpoint state: managed separately by `AsyncPostgresSaver` (`app/agent/checkpointer.py`) for graph replay/resumption. It opens its own connection independent of the application pool.

**Realtime** (`app/runtime/event_bus.py`, `app/runtime/conversation_lock.py`):
- `EventBus` is in-process pub/sub, keyed by conversation. `publish()` is synchronous and never blocks, so a slow subscriber cannot stall generation; each subscriber holds a bounded `asyncio.Queue` (`SSE_QUEUE_MAXSIZE`) and is dropped rather than buffered without limit if it falls behind. Event types: `message.created`, `message.delta`, `message.completed`, `message.cancelled`, `message.failed`, `conversation.updated`.
- `ConversationLock` is an in-process `dict`-backed lock serializing generation per conversation. Correct without a `Lock`/mutex only because acquisition never awaits between the membership check and the insert.
- Both are process-local. A multi-worker deployment would need `LISTEN/NOTIFY` (event bus) and a PostgreSQL advisory lock (conversation lock) instead — the interfaces are kept narrow enough that this is a swap, not a rewrite.

**Frontend** (`ui/src/`): React 19 + TypeScript on Vite, with TanStack Query used only as a cache for the two REST resources — it is deliberately absent from the streaming path.

The selected conversation lives in the URL (`/c/:conversationId`), so a refresh, a bookmark and a second tab all resolve to the same conversation. `ChatPage` reads that route parameter and wires four hooks, all keyed by it:

- `useConversations` — the sidebar list, plus creation and cache invalidation. Also exports `useConversationsRefresh`, the seam that lets the event stream mark the list stale without importing a cache library.
- `useMessages` — the persisted transcript, plus `useMessageCache` giving the stream write access to it. No writer ever invents a row: an event about a message that is not cached triggers a refetch instead.
- `useConversationStream` — one `EventSource` per conversation, tied to the conversation rather than to sending, because the server treats the sender as an ordinary subscriber. Tokens accumulate in a ref and are published to React state once per animation frame, so rendering is decoupled from the model's output rate. Its state carries the conversation id it belongs to, which makes a conversation switch a comparison during render rather than a reset effect.
- `useChat` — sends a turn and reports why one was refused. It owns no message state: the user's own message arrives back over the event stream like everyone else's, so there is one rendering path rather than two.

`Chat.tsx` renders each message as `drafts[id] ?? message.content` — while a turn is in flight the database row is still empty and the text exists only on the wire; the terminal event writes the authoritative content and drops the draft, so the fallback resolves itself.

Assistant messages are rendered through `Markdown.tsx`; user messages are not, so a user typing literal `**` sees it unchanged. A ```` ```mermaid ```` fence is diverted to `MermaidDiagram.tsx` and drawn as SVG. Because content streams in token by token, a fence is frequently incomplete mid-answer — the diagram keeps its last successful render and shows a pending note rather than flickering, and unclosed Markdown resolves itself once the closing marker arrives.

Recovery is deliberately simple. Deltas are not replayable, so the stream re-reads the transcript on every connect and reconnect, and a client that joins mid-generation renders partial text until the terminal event delivers the full content. That is the entire answer to a dropped connection — no `Last-Event-ID`, no server-side replay buffer.

`App.tsx` also routes `/setting` to `SettingPage.tsx`, currently an empty placeholder reserved for a UI over the runtime settings described above.

The SPA does not yet authenticate. `api/client.ts` already sends `credentials: "include"` on every `fetch`, but there is no login screen and `useConversationStream`'s `EventSource` is not opened with `withCredentials`, so against the now session-gated API the browser client is non-functional pending that work.

**LLM** (`app/llm/`). `llm_factory.py` holds a provider registry and returns a LangChain `BaseChatModel`, so the rest of the codebase never names a vendor. `ollama_llm.py` builds `ChatOllama`; `openai_llm.py` builds `ChatOpenAI` and accepts a custom `base_url`, which covers OpenRouter, Groq, DeepSeek and anything else speaking the OpenAI Chat Completions API. An unknown `LLM_PROVIDER` fails at startup with the list of valid values. `system_prompt.py` loads the persona named by `SYSTEM_PROMPT` from `app/prompts/*.txt`, falling back to a built-in prompt if the file is missing or empty — so a bad value degrades to a usable assistant rather than failing startup. Every persona, including that fallback, is composed with a shared `RESPONSE_FORMAT` block describing what the frontend can render (Markdown, mermaid, no LaTeX or raw HTML). That contract belongs to the interface rather than to any one persona, so it lives in code instead of being duplicated across prompt files. The composed prompt is measured against `SYSTEM_PROMPT_TOKEN_BUDGET` and logs a warning when it exceeds it — a warning rather than an error, because a long prompt still works and this module's contract is to degrade rather than block startup.

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
│   │   ├── tools/                                # Tools the agent may choose to call
│   │   │   └── time_tool.py
│   │   ├── context/
│   │   │   ├── conversation_context_builder.py   # Composes summary + history context for one request
│   │   │   ├── summary_context_builder.py        # Reads the durable summary and its watermark (no LLM)
│   │   │   └── history_context_builder.py        # Reads transcript messages after the summary watermark
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
│   │   └── runtime_settings.py                   # RuntimeSettings (frozen dataclass) + RuntimeSettingsHolder
│   ├── database/
│   │   ├── connection.py                         # Sync connection (schema setup only) + the shared async pool
│   │   ├── init_db.py                            # Create database/tables if missing, then run migrations
│   │   └── migrations.py                         # Versioned schema changes to tables that already exist
│   ├── llm/                                      # Model provider selection, isolated from the rest of the app
│   │   ├── llm_factory.py                        # Provider registry; returns a LangChain BaseChatModel
│   │   ├── ollama_llm.py                         # Builds ChatOllama (local models)
│   │   ├── openai_llm.py                         # Builds ChatOpenAI; custom base_url covers OpenRouter/Groq/DeepSeek
│   │   ├── sampling.py                           # Binds runtime sampling params onto the LLM client per provider
│   │   └── system_prompt.py                      # Loads the persona named by SYSTEM_PROMPT, with fallback
│   ├── logs/                                     # Daily log files (gitignored)
│   ├── prompts/                                  # System prompts (persona files) + summarization prompts
│   │   ├── default.txt                           # Fallback persona, selected by SYSTEM_PROMPT
│   │   ├── anna.txt                              # Japanese career-support persona (履歴書 / 職務経歴書 interviewing)
│   │   ├── default_summary_chunk_prompt.txt      # Prompt for summarizing one batch of new messages
│   │   └── default_summary_merge_prompt.txt      # Prompt for merging a chunk summary into the durable summary
│   ├── repositories/                             # Functions for executing SQL against tables.
│   │   ├── conversation_repository.py            # Conversations (owned by a user) (One)->(Many) Messages
│   │   ├── message_repository.py                 # Persistent transcript data. Source of truth for conversation history.
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
│       └── logger.py                             # Logging
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
│       ├── hooks/
│       │   ├── useConversations.ts               # Sidebar list, creation, and cache invalidation for the stream
│       │   ├── useMessages.ts                    # Transcript query + write access to its cache
│       │   ├── useConversationStream.ts          # One EventSource per conversation; owns the live token drafts
│       │   ├── useChat.ts                        # Opens a turn (POST); owns no message state
│       │   └── useTheme.ts                       # Light/dark theme
│       ├── layout/
│       │   ├── ChatPage.tsx                      # Reads the route param and wires the four hooks together
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
├── LICENSE
├── THIRD-PARTY-NOTICES
├── README.md
└── requirements.txt
```
