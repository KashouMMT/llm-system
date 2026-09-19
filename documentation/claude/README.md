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
| `Recycling_Agent_Tools_Plan.md` | **Current** — phases 1–3 live-tested; phase 4 written, untested live; phase 5 (permission modes) spec noted | Catalog→Postgres, or any recycling agent tool / permission-mode work |
| `Recycling_Video_Frames_Plan.md` | **Proposed, not built** | Implementing phase 7 (video). The step-by-step build plan and the code each step needs; the decisions behind it stay in the TODO |

## Conventions

**Write compact, not readable.** These are context-restore notes, not prose —
fragments over sentences, tables and arrows over paragraphs, signatures and argv
over full code blocks. Keep only what changes what a later session does:
decisions, contradictions, exact identifiers and paths, gotchas, open questions.
Density is the goal; a document that reads well but takes three screens to say
what one screen could is the wrong shape.

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

# Notes added by Human User

Try to write your note as compact as possible as you can. Because I want you to save tokens.
Mentioned in multiple places and written here again just to be safe. 
It doesn't need to be human readable so long as you can get to the point and 
context of the topic I want to talk about.