# Design: Session Chaptering (semantic task attribution)

Status: draft, not yet built
Author: written by Claude, from a design conversation with the repo owner
Related: `README.md` (v1 telemetry layer, already built), `adventures-in-ai#34`
(original scoping ticket)

## Problem

`work-ledger` v1 answers "what did this prompt/LLM-call cost" using purely
structural boundaries already present in the transcript (`promptId` for
Turns, `message.id` for Units). That's the right foundation for a live,
zero-setup, deterministic **telemetry** layer, but it doesn't answer the
question the repo owner actually wants answered: **"what did this
_initiative_ cost"** — e.g. "building the v1 dashboard," "chasing the
double-counting bug," "setting up the PR-review Routine." Those initiatives
don't line up with prompt or message boundaries: one initiative can span many
turns, and one turn can touch several initiatives.

That grouping is semantic, not structural — no field in the transcript marks
"this is where initiative X started." Getting it requires reading and
interpreting the content, not just counting lines.

## Goals

- Given a finished (or in-progress) session transcript, produce a
  human-readable outline — **chapters** (an initiative) containing
  **sections** (a step within it) — with each chapter/section attributed its
  share of tokens/cost.
- Keep this fully decoupled from the existing telemetry layer. Chaptering is
  a read-only, offline/batch annotation on top of `Turn`/`Unit` data; it
  must not change how `transcript.py` parses or how the live dashboard
  counts cost.
- Keep the added cost of *running* the chaptering pass itself small and
  visible (it would be self-defeating for a cost-tracking tool to have an
  expensive hidden cost center).
- Work retroactively on a transcript from any point (mid-session or after
  the fact), same as the rest of the tool.

## Non-goals (for this pass)

- Cross-session rollup / "how much did initiative X cost across many
  sessions" — needs chaptering to exist first, called out as future work
  below.
- Recurring-pattern / waste mining (retries, redundant re-reads, repeated
  subagent fan-outs) — same, depends on chapters existing to compare across.
- Real-time chapter boundaries in the live `Live` dashboard — chaptering
  requires content judgment, which is inherently a batch/best-effort pass,
  not a per-second poll. `--detail` (structural, already built) stays the
  live view; chapters are a separate, on-demand report.

## Why not pure heuristics

Considered clustering turns into chapters using only structural/timing
signals — explicit skill invocations, subagent dispatches, long idle gaps
between turns, `AskUserQuestion` calls as pivot points. These are useful
*signals* but insufficient on their own: two consecutive turns can be
structurally identical (both "a paragraph of Bash calls") while belonging to
completely different initiatives, and a single skill invocation can occur
in the middle of an initiative rather than starting one. Heuristics alone
would produce boundaries that are cheap but frequently wrong, which is worse
than a small, visible LLM cost for output someone will actually trust enough
to act on ("cut initiative X").

## Architecture

```
transcript.py (existing, untouched)
  → Turn (per prompt), Unit (per LLM call), each with own cost/tokens
        │
        ▼
chapters.py (new)
  1. Build a compact "outline input": for every Turn, its prompt snippet;
     for every Unit within it, its label (text snippet / "Skill: X" /
     "Subagent: Y") and cost. This is already-extracted short text, not
     full message content — keeps the summarization call's own input small.
  2. Send that compact outline to a single batched call to a cheap/fast
     model (Haiku) with a fixed prompt (see below), asking for chapter/
     section boundaries + short titles as JSON, referencing turns/units by
     an index rather than re-emitting their content.
  3. Parse the JSON response into Chapter/Section objects that reference
     the existing Turn/Unit objects (no new cost data invented here - cost
     rollup for a chapter/section is a pure sum over the Turns/Units it
     contains).
        │
        ▼
cli.py: new subcommand `work-ledger chapters [--transcript PATH]`
  Prints a nested tree: Chapter → Section → (optionally) Turn, each with
  its own $ and token rollup, sorted by cost descending so the most
  expensive initiative surfaces first.
```

### Data model (`chapters.py`)

```python
@dataclass
class Section:
    title: str
    turn_indices: list[int]   # indices into the ordered turn list

@dataclass
class Chapter:
    title: str
    sections: list[Section]

    @property
    def turn_indices(self) -> list[int]:
        return [i for s in self.sections for i in s.turn_indices]
```

Cost/token rollups for a `Chapter`/`Section` are computed by summing the
`cost_usd`/`input_tokens`/`output_tokens` of the referenced `Turn` objects
(which already sum their own `Unit`s) — no separate cost fields stored on
Chapter/Section, so there is exactly one source of truth for cost
(`Unit.own_*` / `Unit.subagent_*`) and no way for the two layers to drift
apart.

### The summarization call

- **Model**: Haiku 4.5 — cheapest tier, and this is a summarization/
  classification task over a few KB of already-short text, well within its
  capability.
- **Input**: numbered list of turns, each turn showing its prompt snippet and
  the labels (not full text) of its units, e.g.:
  ```
  [0] (12:03) "How do we track how much our work is costing us..."
      units: text, text, Skill: dataviz, text
  [1] (12:05) "Write a design doc. Then ask the sub agent to review"
      units: text, Bash, Write, text
  ...
  ```
- **Output**: strict JSON — a list of chapters, each with a title and a list
  of sections, each section listing the turn indices it covers. Validate
  indices are in range and cover every turn exactly once (any turn not
  assigned falls back into an "Unsorted" chapter rather than silently
  dropped — mirrors the existing "unknown-model cost shows `?`, never
  silently 0" philosophy already in `pricing.py`).
- **Cost of the pass itself**: outline input is small (a few hundred bytes
  per turn); for a 50-turn session this is roughly 5-15K input tokens and a
  few hundred output tokens — at Haiku rates, well under $0.05 per session.
  The CLI should print this cost alongside the chapter output ("chaptering
  this session cost $0.0031") so the tool's own overhead stays visible,
  consistent with the project's cost-transparency goal.
- **Failure mode**: if the call fails or returns invalid JSON, fall back to
  one chapter ("Unsorted") containing every turn, and say so explicitly —
  never fail silently or block the rest of the tool.

## CLI surface

```
work-ledger chapters                       # chapter/section tree for the active session
work-ledger chapters --transcript PATH     # for a specific transcript
work-ledger chapters --json                # machine-readable output, for later cross-session tooling
```

Sample terminal output (illustrative):

```
Chapters — session 0daf9882... ($5.42 total, chaptering cost $0.0031)

▾ Build work-ledger v1 dashboard           $3.10  (61%)
    Read existing repo, scope decisions      $0.40
    Write transcript.py / pricing.py / cli.py $2.70
▾ Fix usage double-counting bug            $1.80  (33%)
    Diagnose duplicate message.id lines       $0.60
    Rewrite dedup logic, verify              $1.20
▾ Set up PR-review Routine                 $0.52  (10%)
```

## Future work this unblocks

- **Cross-session rollup**: once chapters exist per-session, aggregating
  "how much did initiative X cost across sessions" is a matter of matching
  chapter titles/themes across multiple chaptered transcripts (possibly
  another small LLM pass to cluster similar chapter titles together, or a
  simple embedding-similarity match — deferred, not designed here).
- **Recurring-pattern / waste mining**: once there's a stable initiative
  grouping, look for the same expensive pattern recurring across chapters
  or sessions (e.g. repeatedly re-reading the same files, repeated subagent
  dispatches for near-identical research). This is naturally a second pass
  over chaptered data, not a new parsing concern.
- **Deterministic-tool substitution**: once a recurring, expensive pattern
  is identified (e.g. "every session re-derives the pricing table by asking
  Claude"), the fix is a one-off, idiosyncratic script or tool for that
  specific pattern — not a generic framework. This is expected to be
  fix-one-at-a-time work driven by what chaptering/mining actually surfaces,
  not something to build ahead of the data.

## Open questions

1. Chapter granularity: should very short sessions (a handful of turns)
   always get one chapter, or should the model be told a minimum/maximum
   chapter count? Leaning toward no hard limit — let the model decide, and
   accept that very short sessions may just come back as a single chapter.
2. Should `--detail`'s existing Unit-level view stay separate from chapters,
   or should chapters be viewable as a filter/lens on top of `--detail`
   (e.g. `--detail --chapter "Fix usage double-counting bug"`)? Leaning
   toward a separate command for now (simpler), revisit if the two views
   feel like they want to merge.
3. Caching: since chaptering costs real money and a finished session's
   turns don't change, should results be cached to disk (e.g. next to the
   transcript) so re-running `work-ledger chapters` on the same transcript
   doesn't re-pay for the Haiku call? Leaning yes — simple JSON cache
   keyed on transcript path + byte offset chaptered so far, invalidated
   only when new turns are appended.
