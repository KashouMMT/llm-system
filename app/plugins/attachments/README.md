# attachments

One tool: `read_attachment`. It is how the model reads back a PDF or
plain-text file the user attached, on any turn after the one that uploaded
it — images are visible to the model directly (as content blocks) only on
the turn they arrive, and never through this tool.

## Files

| File | Contents |
|---|---|
| `__init__.py` | `PLUGIN` — exposes `read_attachment`, built via `make_attachment_tools` |
| `tools.py` | The tool itself: ownership check, extraction, pagination, every failure mode |

## What it does

`read_attachment(attachment_id, page=1)`:

1. Resolves identity from `config["configurable"]["thread_id"]` (the run
   configuration), **never** from the model-supplied `attachment_id` — the
   id is looked up and its `conversation_id` compared, so a model cannot
   read a file from a conversation that is not this one.
2. Returns image files as metadata only ("visible to you only on the turn
   it was attached").
3. Extracts PDF text via `pypdf`, or plain text via `app.utils.detect`'s
   UTF-8/Shift_JIS decoding, both inside `asyncio.to_thread` so extraction
   never blocks the event loop that also serves SSE.
4. Paginates at ~8,000 characters, telling the model which page it got and
   how many exist.

## Failure modes, each with its own message

A password-protected PDF, a PDF with no text layer at all (almost
certainly scanned), a PDF where only *some* pages have no text (flagged on
every page of output, not just the first, so the model never answers from
a typed cover page as if it were the whole document), and a file type this
tool cannot read at all. Every one is reported back to the model as text —
never raised — because an unreadable attachment is data the user supplied,
not an application failure.

## Why this exists as a separate plugin from documents

Reading an attachment and generating a document are opposite directions of
the same file-handling problem, but they have no code in common — no
shared schema, no shared renderer, no shared identity logic beyond the
pattern (never the implementation) of trusting the run configuration over
model-supplied arguments. Splitting them keeps each plugin's "delete the
folder, the capability is gone" test true.
