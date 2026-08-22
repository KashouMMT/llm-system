# llm-system

A conversational LLM system built on LangChain, LangGraph, and Ollama, with PostgreSQL-backed persistence and rolling summarization for long-running conversations. Runs as a CLI or a FastAPI server; a React UI (empty shell, not yet implemented) is intended as the eventual frontend.

## Requirements

- Python 3.11+
- PostgreSQL (reachable instance; the app creates its database and tables on startup if they don't exist)
- [Ollama](https://ollama.com) running locally with the target model pulled

## Setup

```bash
pip install -r requirements.txt
```

Configure via a `.env` file (all values optional, defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_NAME` | `dolphin-phi:latest` | Ollama model tag |
| `TEMPERATURE` | `0.7` | Sampling temperature |
| `MAX_TOKENS` | `512` | Max tokens generated per response (`num_predict`) |
| `CONTEXT_WINDOW` | `8192` | Model context window (`num_ctx`) |
| `TOP_P` | `0.9` | Nucleus sampling |
| `SYSTEM_PROMPT` | `default` | Filename (without `.txt`) under `app/prompts/` |
| `SUMMARY_TOKEN_THRESHOLD` | `1200` | Estimated token count of unsummarized messages that triggers summarization |
| `MAX_CONTEXT_HISTORY_MESSAGES` / `RECENT_MESSAGE_LIMIT` | `20` | Max recent (post-summary) messages fed into each turn |
| `MAX_CHECKPOINT_MESSAGES` | `50` | Max messages kept in LangGraph's checkpoint state after a turn |
| `MAX_UNSUMMARIZED_MESSAGES` | `12` | Hard cap that forces summarization regardless of token estimate |
| `MAX_USER_INPUT_CHARS` | `4000` | Max characters accepted in a single user message |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CONSOLE_LOG` | `false` | Also log to console |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `localhost` / `5432` / `llm_system` / `postgres` / `postgres` | PostgreSQL connection |

## Running

```bash
python -m app.main               # CLI chat
python -m app.main --api         # FastAPI server on :8000
python -m app.main --log-level DEBUG
```

CLI commands: `/exit` to quit, `/history` to print the current conversation's transcript.

## Architecture

**Composition root.** [app/runtime/application.py](app/runtime/application.py) (`Application`) is an async context manager that owns the lifecycle of every shared resource: it initializes the database, loads the system prompt, builds the LLM client, opens the LangGraph PostgreSQL checkpointer, and wires the context builders, `AgentGraph`, `SummarizationService`, and `ChatService`. `app/main.py` opens one `Application` and hands it to either the CLI loop or the FastAPI app.

**Request flow.** `ChatService.chat_stream` (called from the CLI or the `/chat/stream` endpoint) streams tokens from `AgentGraph`, buffers the full response, and — only after the graph completes successfully — persists the user/assistant turn via `ConversationRepository` and kicks off summarization as an untracked background `asyncio.Task`. Summarization never blocks or can fail the chat response.

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

**Summarization** (`app/services/summarization_service.py`): after each turn, `ChatService` schedules `SummarizationService.trigger_if_needed`, which estimates tokens (`len(text) // 4`) over messages not yet summarized and, if over `SUMMARY_TOKEN_THRESHOLD` (or `MAX_UNSUMMARIZED_MESSAGES` is exceeded), generates a chunk summary via the LLM, merges it into the existing summary via a second LLM call, and advances the watermark — all through `SummaryRepository`.

**Persistence** — two separate stores:
- Application data (PostgreSQL, `app/database/`, `app/repositories/`): `conversations`, `messages`, `conversation_summary_state` (current summary + watermark), `conversation_summaries` (historical chunk log). Tables are created on startup if missing.
- LangGraph checkpoint state: managed separately by `AsyncPostgresSaver` (`app/agent/checkpointer.py`) for graph replay/resumption.

**LLM.** `app/llm/llm_factory.py` currently wraps `ChatOllama` only. `app/llm/prompt_factory.py` and the `app/prompts/*.txt` persona files (loaded via `SYSTEM_PROMPT`) allow swapping system prompts without code changes.

## API (`--api` mode)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/conversations` | Create a conversation |
| `GET` | `/conversations` | List conversations |
| `GET` | `/conversations/{id}/messages` | Get a conversation's transcript |
| `POST` | `/conversations/{id}/chat/stream` | Streamed chat turn (`text/plain`, body: `{"message": str}`) |

CORS is currently restricted to `http://localhost:5173` (the Vite dev server for `ui/`).

## Folder Structure

```
llm-system/
├── app/                                          # Main LLM Related Files
│   ├── main.py                                   # Main entry point (CLI or --api)
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
│   ├── config/
│   │   └── settings.py                           # Load env values, other constant variables
│   ├── database/
│   │   ├── connection.py                         # Create connection with database
│   │   └── init_db.py                            # Initialize database and tables if not exist
│   ├── llm/                                      # LLM Folder. In future, will support LLM switching.
│   │   ├── llm_factory.py                        # Currently supports Ollama client
│   │   └── prompt_factory.py                     # Prompt loading; in future, system prompt switching from user side
│   ├── logs/                                     # Logs
│   ├── persona/
│   │   └── load_prompt.py                        # Load prompt from prompts folder below
│   ├── prompts/                                  # Character behavior and personality for LLM. Basically system prompts.
│   ├── repositories/                             # Functions for executing SQL against tables.
│   │   ├── conversation_repository.py            # Conversations (One)->(Many) Messages
│   │   ├── message_repository.py                 # Persistent transcript data. Source of truth for conversation history.
│   │   └── summary_repository.py                 # Durable summary state + summary chunk history per conversation
│   ├── runtime/
│   │   ├── application.py                        # Initializes entire app. Composition root and lifecycle owner.
│   │   ├── cli.py                                # CLI interface for app.
│   │   └── server.py                             # FastAPI REST API for app.
│   ├── services/
│   │   ├── chat_service.py                       # Main chat service; schedules background summarization after a turn
│   │   └── summarization_service.py              # Generates and persists durable conversation summaries (LLM calls)
│   └── utils/
│       └── logger.py                             # Logging
├── ui/                                           # React UI. Communicates with FastAPI. Empty shell, not yet implemented.
├── LICENSE
├── README.md
└── requirements.txt
```
