# Context builder — planned work

## Structured slot memory (planned `SlotContextBuilder`)

### Problem

The durable summary is prose produced by an LLM merge
(`SummarizationService._merge_summary`). Every merge regenerates the whole
text, so every fact in it is re-rolled on every summarization. The
preservation rules in `prompts/default_summary_merge_prompt.txt` make that
unlikely to lose a value, not impossible — and the failure is
non-deterministic, which makes it hard to test and hard to reproduce.

Observed on 2026-09-05: a 履歴書 intake conversation kept the user's name,
date of birth, phone and email correctly, but lost the *state* around them —
which fields the user had explicitly deferred, that drafted 志望動機 /
自己PR text had been rejected, and that the user had already asked for the
document to be generated anyway. Those live as one line under `OPEN_ITEMS`
and carry no more weight through a merge than a piece of small talk.

### Why prose is the wrong shape for this

The document-generation flow does not need "a good summary of the
conversation". It needs a known, finite set of 履歴書 / 職務経歴書 fields,
each with a current value and a current status. That set is known in
advance, so nothing has to be inferred or retrieved semantically.

### Proposed shape

A third context source alongside summary and history:

```
prepared_context = [
    *summary_context.messages,     # prose: everything not a slot
    *slot_context.messages,        # structured: the document fields
    *recent_history,
]
```

`SlotContextBuilder` reads a per-conversation slot record and renders it
verbatim into a system message. It never calls an LLM — same contract as
`SummaryContextBuilder`. Writing the slots is a separate concern, done
out-of-band alongside summarization.

Sketch of the record:

```json
{
  "full_name":      { "value": "John Smith", "status": "provided" },
  "name_kana":      { "value": null,         "status": "deferred_by_user" },
  "date_of_birth":  { "value": "1989-02-14", "status": "provided" },
  "address":        { "value": null,         "status": "deferred_by_user" },
  "phone":          { "value": "090-5837-2416", "status": "provided" },
  "email":          { "value": "johnsmith@gmail.com", "status": "provided" },
  "education":      { "value": null,         "status": "deferred_by_user" },
  "work_history":   { "value": null,         "status": "deferred_by_user" },
  "certifications": { "value": "ITPEC IP, ITPEC FE, JLPT N3",
                      "status": "partial" },
  "motivation":     { "value": "…", "status": "drafted_awaiting_approval" }
}
```

Statuses worth distinguishing: `missing`, `provided`, `partial`,
`deferred_by_user`, `drafted_awaiting_approval`, `approved`.

### What this buys

- Values are copied, never regenerated — no per-merge loss.
- `deferred_by_user` becomes an explicit, checkable state rather than
  something the model has to re-infer from prose. This is what the
  document-generation guard should read, so an explicit user request to
  generate with blanks is honoured instead of refused.
- Testable: assert the phone number still equals the string the user typed
  after N turns, instead of eyeballing a summary.
- The prose summary keeps its job — everything that is *not* a slot.

### Deliberately not doing

Not adopting a memory framework (Mem0, Zep, LangMem). Those own the
retrieval loop and provide semantic recall over an open-ended memory set.
The requirement here is the opposite: a closed, known set of keys. A table
and a dataclass cover it, with no dependency that could later dictate the
shape of the agent loop.

### Open questions

- Storage: new `conversation_slots` table, or a JSONB column on the
  existing summary state row? The latter keeps the watermark and the slots
  updating together.
- Extraction: a dedicated small LLM call per turn, or reuse the
  summarization call and have it emit slots alongside prose? The second is
  cheaper but couples slot freshness to the summarization trigger, which
  can be many turns apart.
- Slot definitions should be per document type (履歴書 vs 職務経歴書) and
  probably belong next to the document templates, not here.

---

## RAG document context (placeholder)

`ConversationContextBuilder.build` already reserves the ordering for a
`rag_context_builder`. Not started.
