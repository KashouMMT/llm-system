GPU/model constraints (RTX 3050 4GB)

Ollama will silently OOM or fall back to CPU (much slower, or a crash) if you pick a larger model later, or even the current one under a longer context. Worth confirming now whether qwen3.5:9b is fully resident in VRAM or already partially offloading to CPU — that changes how much headroom you actually have.
CONTEXT_WINDOW defaults to 4096 tokens in settings.py, but nothing in ConversationContextBuilder or agent_node.py counts tokens before sending — only message count is bounded (MAX_CONTEXT_HISTORY_MESSAGES, MAX_CHECKPOINT_MESSAGES). A few long messages or one large tool result can blow past the context window with no warning; Ollama will either truncate silently or error, and on constrained VRAM this is more likely to surface as a hard failure than on a bigger card.

Concurrency (matters more once you add the API/UI)

Application holds one shared llm client. If the FastAPI server ever receives two concurrent chat requests, both compete for the same 4GB of VRAM — expect serialization at best, OOM/crash at worst. There's no request queue or per-conversation lock in server.py today.
Two concurrent requests against the same conversation_id (e.g. a double-click in a future UI) would both drive the same LangGraph thread_id through the checkpointer simultaneously — that's a real risk for corrupted/interleaved checkpoint state, not just a performance issue.
Every repository call opens a fresh psycopg connection with no pooling. Under concurrent API load this can exhaust Postgres' max_connections well before it exhausts anything else.

Data/persistence gotchas

CREATE TABLE IF NOT EXISTS doesn't migrate — any future schema change (new column, changed type) will silently no-op against an existing local DB, then fail at the first write with a confusing column-not-found error. Worth remembering this every time you touch init_db.py, or moving to a real migration tool (Alembic) before the schema stabilizes further.
The LangGraph checkpoint tables (AsyncPostgresSaver) grow with every graph step and are never pruned — compact_checkpoint_state_node only trims what's held in state, not historical checkpoint rows already written to Postgres. Long-running dev use could accumulate checkpoint bloat with no cleanup path yet.
A tool with side effects (once you add one beyond get_current_time) executing successfully, followed by a later node failure, means the turn isn't persisted to the app DB at all (chat_service.py's except block persists nothing) — but the side effect already happened. notes.txt item 12 already flags a related ordering issue; this is the sharper version of it once tools do more than read the clock.

Environment-specific

app/main.py forces SelectorEventLoop explicitly on Windows — a common workaround for ProactorEventLoop + psycopg/asyncio quirks. If you ever add a tool or dependency that needs subprocess support (Proactor-only on Windows), this pinned loop could conflict; worth remembering why it's there if it ever needs revisiting.
.env currently defaults to postgres/postgres — fine solo-dev, but a reminder to change before this touches anything beyond localhost.
No log rotation on app/logs/*.log — fine for now, will accumulate over a long dev cycle.

None of these are urgent — they're the kind of thing that's cheap to fix now and expensive to debug later, especially the token-window and concurrency ones given your VRAM ceiling.

---

## Config injection refactor
- LLMFactory.create() is a static method reading module constants
  (MODEL_NAME, TEMPERATURE, MAX_TOKENS, CONTEXT_WINDOW, TOP_P) directly.
  No object exists to inject config into — blocks both multi-provider
  support and runtime-configurable model settings. Fix: create()
  should take an LLMConfig object built by Application.

- SummarizationService takes token_threshold / max_unsummarized_messages
  as constructor args with module-constant defaults
  (SUMMARY_TOKEN_THRESHOLD, MAX_UNSUMMARIZED_MESSAGES). Python freezes
  default arg values at import time, so if these ever become
  dynamically reloadable, this silently stops picking up changes.
  Fix: wrap in a SummaryConfig dataclass, pass in as a required
  arg, no default.

- HistoryContextBuilder (max_history_messages) and SummarizationService
  (max_unsummarized_messages) share an invariant:
  MAX_UNSUMMARIZED_MESSAGES <= MAX_CONTEXT_HISTORY_MESSAGES, otherwise
  messages can fall out of history before ever being captured in a
  summary. Currently unenforced. Fix: group both into one
  ContextConfig dataclass, validate the invariant in __post_init__.

- General rule for what to inject vs. leave as a plain settings.py
  constant: only inject values that are (a) a plausible future
  runtime/admin-configurable knob AND (b) have an object to hand them
  to. DB_*, DATABASE_URL, LOG_LEVEL, CONSOLE_LOG stay as-is
  (bootstrap-time, no object exists yet to inject into).
  MAX_USER_INPUT_CHARS stays as-is (used in a Pydantic Field
  max_length, which is also evaluated at import time — would need a
  runtime validator instead, not worth it for how rarely this changes).

## Prompt content cleanup (separate from config refactor)
- SUMMARY_CHUNK_PROMPT and SUMMARY_MERGE_PROMPT in settings.py are
  content, not configuration (80 lines of prompt text in a settings
  file). Move to app/prompts/summary_chunk.txt and
  summary_merge.txt, load via the existing load_prompt() /
  PromptFactory machinery instead of importing as string constants.

## Documentation
- Keep README.md env var table in sync with settings.py when adding
  new settings — it's already drifted twice (CONTEXT_WINDOW,
  MAX_UNSUMMARIZED_MESSAGES, MAX_USER_INPUT_CHARS were stale/missing
  as of 2026-08-23).

--- 

# Notes — Applying AI Evaluation Results (Code-Level)

## Core principle
The AI has no memory of past mistakes. "Don't do that again" changes nothing.
Every correction is an engineering change we make.

  Must NEVER happen  →  enforce in CODE (deterministic)
  Preference / style →  enforce in PROMPT (probabilistic)

Client sentence:
"The AI's instructions handle tone and style; the program handles facts."

## The only 4 levers in this codebase

| # | Lever                          | Where                          | Reliability   |
|---|--------------------------------|--------------------------------|---------------|
| 1 | System prompt text             | app/prompts/anna.txt           | Probabilistic |
| 2 | Tool docstring + return shape  | app/agent/tools/*.py           | Probabilistic |
| 3 | Retrieval code inside the tool | job_search_tool body           | DETERMINISTIC |
| 4 | Validation node in the graph   | app/agent/graph.py             | DETERMINISTIC |

(+ model params: TEMPERATURE / TOP_P in settings.py — blunt, global)

## ② Hallucination → new graph node (NOT a prompt fix)

Current flow has NO output inspection:
  agent ─┬─ tool call → tools → agent
         └─ final answer → compact_checkpoint_state → END

Fix — insert validation:
  agent ─┬─ tool call → tools → agent
         └─ final answer → validate_grounding → compact → END
                                │
                                └─ failed → agent (retry, violation named)

New file: app/agent/nodes/validate_grounding_node.py
  allowed_ids = {job ids the tools actually returned this turn}
  cited_ids   = regex over the answer text
  invented    = cited_ids - allowed_ids
  if invented: push corrective SystemMessage, route back to agent
  retry cap 2 → fall back to fixed "該当する求人が見つかりませんでした"

Why it works: it's a set difference. Can't be talked out of, doesn't decay
at turn 40, identical on Qwen and GPT. This is why 0% is an honest target.

PREREQUISITE: answers must cite IDs (【求人ID: J-00123】).
Free-form prose cannot be checked. The output FORMAT is the enforcement.

## ③ RAG accuracy → split by reading the retrieval log

Same user symptom ("it didn't find my job"), two different files.

A) Right job NOT retrieved  → search-side, inside the tool
   - SQL WHERE too strict → zero results
   - limit/TOP_K too small → correct job ranked 21st, never seen
   - Japanese tokenization: default tsvector won't split バックエンドエンジニア
   - synonym table; keyword-vs-vector score weighting; add re-rank pass

B) Job WAS retrieved but unused → answer-side
   1. Too many results — 50 JSON records buries it. Return 5–10.
   2. Bad ordering — attention degrades mid-input. Best match first.
   3. Token budget — CONTEXT_WINDOW 16384 minus ~2,300 prompt minus history
      minus 2,048 output. Ollama truncates from the FRONT, silently.
      → return summaries, not full job descriptions.

Without this split you spend weeks tuning the half that already worked.

## ④ Tool selection → the DOCSTRING is the prompt

@tool docstrings are serialized into the JSON tool schema and sent on EVERY
call via llm.bind_tools(). Not documentation — live prompt text, sitting
closer to the decision than anything in anna.txt.

So: bad tool routing → edit the docstring, NOT the system prompt.
Write the negative case explicitly:

    """Search stored job postings by conditions and meaning.

    Use this when the user wants to find actual job openings.
    Do NOT use this for resume writing, motivation statements, or general
    career advice — answer those directly without calling any tool.
    """

Cheapest, highest-leverage fix in the system.
Fewer tools route better than more. Two similar tools > misrouting.

## ⑤ Human evaluation → eval harness (build in Sprint 2)

evals/run_eval.py — replay dataset, fresh thread_id per case:
    answer, tools_called, retrieved_ids, grounding_ok, expected_tool

  Auto-scored: ② ④ ⑥ ⑦
  Needs human column: ① ③ ⑤

The DATASET is the deliverable, not the script.
Every conversation rated ≤2 becomes a row → grows into a regression suite.
git diff on the results file between runs catches "fixed A, broke B".

Operating rules:
  - 1 complaint  → test case only, do NOT change the prompt
  - 3+ occurrences of a pattern → then change the prompt
  Reason: prompts edited per-comment become long, self-contradictory,
  and quality drops (fix one, break two).

## When a prompt edit IS the right fix

| Symptom                                       | Prompt fix? |
|-----------------------------------------------|-------------|
| Anna forgot identity / wrong language          | YES         |
| Too formal, wrong 敬語 level                   | YES         |
| Skipped a required 職務経歴書 section          | YES (checklist) |
| Called search tool for "write my motivation"   | NO → docstring |
| Cited a job that doesn't exist                 | NO → validation node |
| Returned Osaka jobs when asked for Tokyo       | NO → SQL filter |

DISCIPLINE: every prompt edit → re-run the FULL dataset.
Prompts are global; a rule added at line 90 can break an unrelated case.
This is why the improvement loop closes back on itself instead of ending
at "apply fix".

---

LangFuse