# Design records and R&D notes

Internal working documents: the *reasoning* behind decisions, not just their
outcome. Written so that a session with no conversation history can read one and
resume with the same understanding.

**This folder is Claude's to maintain** — files here may be created, updated and
deleted without asking, which is the exception to the rule in `CLAUDE.md` that
nothing is written unless requested. Everything else under `documentation/` is
reference to read, not to edit.

It is also the right home for anything worth remembering *about the project*,
in preference to Claude's own memory: a file here is versioned, diffable, and
readable by a handoff session or by Katsu-san.

These are not client deliverables. Client-facing documents live in
`documentation/markdown/`, `documentation/docx/` and `documentation/pdf/`, and
are written in a different voice for a different audience. The client-approved
reference workbooks the document renderers were built from are in
`documentation/other/`.

| Document | Status | Read it when |
|---|---|---|
| `Recycling_Estimator_TODO.md` | **Current** | Any work on `app/plugins/recycling/` — the detection pipeline, the catalog, or the video path |

## Conventions

**Say what is decided, and why the alternative lost.** A decision recorded
without its reasoning gets re-litigated every few weeks, and a reversal is
impossible to judge without knowing what the original trade was.

**Record reversals in place rather than rewriting history.** The recycling
document reverses its own detector decision twice; both reversals are visible,
which is what makes the current position trustworthy.

**Date anything that is a snapshot.** Status headers, probe results and
"currently unproven" claims all go stale, and an undated stale claim is worse
than no claim.

**Mark a superseded document at the top.** Leave it in place — the reasoning is
still worth reading — but never leave a reader to discover halfway down that it
no longer describes reality.

**Keep measurements separate from plans.** A probe result is evidence; a phase
table is intent. The recycling document keeps probe findings with their raw
numbers and their caveats — including what the probe did *not* test — so a
later reader can judge the evidence rather than inherit a conclusion.
