# clock

The minimal plugin — one tool, one command, no dependencies on storage or
the database. Kept intentionally small as the reference shape every other
plugin's `PLUGIN` declaration is modeled on.

## Files

| File | Contents |
|---|---|
| `__init__.py` | `PLUGIN` — a `ToolPlugin` exposing `get_current_time` as a tool and `/clock` as a command namespace |
| `tools.py` | `now_jst_text()` (the shared JST formatter) and `get_current_time` (the `@tool`-wrapped LangChain tool) |
| `commands.py` | `handle_clock` — dispatches `/clock <subcommand>`; today only `time` |

## What it exposes

- **Tool** `get_current_time()` — callable by the model, JST, no arguments.
- **Command** `/clock time` — deterministic, never reaches the LLM. Same
  answer as the tool, formatted by the same `now_jst_text()` helper, so the
  two paths can never drift into reporting the time differently.

## Why JST, not the host's local zone

Every document this app's `anna` persona produces is dated for a Japanese
reader. A server running in another region would otherwise silently report
a date one day out. See `app/utils/jst.py` for the shared `JST` constant —
it lives in `app/utils/`, not here, because the document-generation plugin
needs it too, and a plugin is never allowed to import another plugin.

## Why the folder is named "clock", not "time"

So that `import time` (the standard library module) inside this package's
own files is unambiguous to a reader. Python 3 would resolve it correctly
either way; the confusion is the cost avoided.
