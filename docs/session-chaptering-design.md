# Design: Session Chaptering (semantic task attribution)

Status: implemented (`work_ledger/chapters.py`, `chapters` subcommand) - see
`docs/example-session.md` for real output. Bulk/retroactive (`--all`) and
the visual report (`--report`) shipped as follow-on PRs on top of this.
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
- **Chapters must drill down into the existing per-unit `--detail` view.**
  Seeing "Fix double-counting bug cost $1.80" is not the end goal — the
  point of chaptering is "here's what to cut," and deciding what to cut
  means looking at the actual tool calls that made up that $1.80. This is
  explicitly called out (not just a nice-to-have) per the repo owner: the
  two views must be linked, not two disconnected reports you manually
  cross-reference. See CLI surface below for the concrete design.

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
transcript.py (the deterministic telemetry layer chaptering builds on -
               not part of this design; it happened to also gain a
               separate double-counting fix and Unit refactor in the same
               PR that shipped chaptering, see PR #1)
  → Turn (per prompt), Unit (per LLM call), each with own cost/tokens
        │
        ▼
chapters.py (new)
  1. Build a compact "outline input": for every Turn, its prompt_id and
     prompt snippet; for every Unit within it, its label (text snippet /
     "Skill: X" / "Subagent: Y") and cost. This is already-extracted short
     text, not full message content — keeps the summarization call's own
     input small.
  2. Send that compact outline to a single batched call to a cheap/fast
     model (Haiku 4.5) using enforced structured output (see below), asking
     for chapter/section boundaries + short titles, referencing turns by
     their stable `prompt_id` rather than re-emitting their content.
  3. Validate the response partitions turns correctly (see Validation
     below), then build Chapter/Section objects that reference the
     existing Turn/Unit objects (no new cost data invented here — cost
     rollup for a chapter/section is a pure sum over the Turns/Units it
     contains).
        │
        ▼
cli.py: new subcommand `work-ledger chapters [--transcript PATH] [--detail]`
  Prints a nested tree: Chapter → Section, each with its own $ and token
  rollup, sorted by cost descending so the most expensive initiative
  surfaces first. With `--detail`, each Section additionally expands into
  the existing per-unit rows (see Linking to `--detail` below) — this is
  the drill-down from "this initiative cost $X" to "here's what to cut."
```

### Data model (`chapters.py`)

```python
@dataclass
class Section:
    title: str
    prompt_ids: list[str]   # Turn.prompt_id values, not positional indices

@dataclass
class Chapter:
    title: str
    sections: list[Section]
    category: str   # one of a fixed, closed taxonomy - see CATEGORIES in chapters.py

    @property
    def prompt_ids(self) -> list[str]:
        return [pid for s in self.sections for pid in s.prompt_ids]
```

`category` (added alongside the free-text `title`) is a fixed enum, not
free text — it exists specifically so `work-ledger export` can report
category rollups without ever transmitting a chapter's actual title, which
can describe real project/business specifics. Older cached chapter files
predate this field and default to `"other"`, same as any other
frozen-prefix cache migration in this module.

Turns are referenced by `Turn.prompt_id` (already the dict key in
`TranscriptTailer.turns`), not by position in the ordered turn list.
Indices would tie chapter data to a specific enumeration snapshot and
complicate caching (see Open Questions); `prompt_id` is already stable and
free.

Cost/token rollups for a `Chapter`/`Section` are computed by summing the
`cost_usd`/`input_tokens`/`output_tokens` of the referenced `Turn` objects
(which already sum their own `Unit`s) — no separate cost fields stored on
Chapter/Section, so there is exactly one source of truth for cost
(`Unit.own_*` / `Unit.subagent_*`).

### The summarization call

- **Model**: Haiku 4.5 — cheapest tier, and this is a summarization/
  classification task over a few KB of already-short text, well within its
  capability. Haiku 4.5 supports enforced structured output (confirmed).
- **Input**: numbered list of turns, each turn showing its `prompt_id`,
  timestamp, and prompt snippet, plus the labels (not full text) of its
  units, e.g.:
  ```
  [cdd6a46d...] (12:03) "How do we track how much our work is costing us..."
      units: text, text, Skill: dataviz, text
  [a1b2c3d4...] (12:05) "Write a design doc. Then ask the sub agent to review"
      units: text, Bash, Write, text
  ...
  ```
- **Output enforcement**: use `output_config: {"format": {"type":
  "json_schema", "schema": ...}}` (Python: `client.messages.parse()` with a
  Pydantic model) rather than a prompted "return JSON" convention. This is
  a real, current Claude API mechanism (confirmed against the `claude-api`
  skill, supported on Haiku 4.5) that constrains the response to validate
  against the schema server-side, which eliminates most of the
  index-hallucination / malformed-output failure modes a prompted
  convention would leave to chance — parsing/repair logic stays a fallback
  for the remaining cases (refusal, `max_tokens` truncation), not the first
  line of defense. Schema: a list of chapters, each with a `title` and a
  list of sections, each section listing the `prompt_id`s it covers.
  Caveats to carry into implementation: schemas with recursive structure
  aren't supported (not needed here — this schema is flat), first use of a
  new schema shape has a one-time compilation-cost latency hit (cached 24h
  after), and `stop_reason: "refusal"` or `"max_tokens"` both mean the
  response may not conform — handle both before assuming the shape is
  valid.
- **Validation (partition correctness)**: schema enforcement guarantees
  well-formed JSON, but not that every turn is covered exactly once — the
  model could still legitimately assign the same `prompt_id` to two
  sections (one initiative's work plausibly touching the same turn as
  another) or omit one. After parsing, explicitly check every `prompt_id`
  in the transcript appears in exactly one section:
  - **Missing** turns fall back into an "Unsorted" chapter rather than
    being silently dropped — mirrors the existing "unknown-model cost
    shows `?`, never silently 0" philosophy already in `pricing.py`.
  - **Duplicate** turns (assigned to more than one section) keep only the
    first assignment encountered and drop the rest, logging which
    chapter(s) lost the turn — this is the fix for the double-counting gap
    the review caught: without it, a turn assigned to two chapters would
    have its cost summed twice, silently inflating the visible total above
    the real session cost.
- **Cost of the pass itself**: the outline input is small (a few hundred
  bytes per turn) but the actual request also carries model/schema
  instruction overhead on top of that — budget mentally for "outline size
  plus a few hundred to ~1-2K tokens of fixed scaffolding," not outline
  size alone. For a 50-turn session this totals roughly 5-15K input
  tokens; output tokens scale with turn count (every turn's `prompt_id`
  must be enumerated at least once in the response), so a much longer
  session sees proportionally more output tokens even though the total
  stays cheap in absolute terms (well under $0.05 for a 50-turn session at
  Haiku rates). The CLI should print this cost alongside the chapter
  output ("chaptering this session cost $0.0031") so the tool's own
  overhead stays visible, consistent with the project's cost-transparency
  goal.
- **Failure mode**: if the call fails, returns `stop_reason: "refusal"`, or
  hits `"max_tokens"` before completing, fall back to one chapter
  ("Unsorted") containing every turn, and say so explicitly — never fail
  silently or block the rest of the tool.

### Linking to `--detail` (decided — key requirement, not optional)

Chapters and `--detail` share the same underlying data (`Turn`/`Unit`
objects from `transcript.py`) — chaptering only adds a grouping label on
top, it never invents new rows. That makes the link mechanical rather than
a new rendering system:

- `chapters.py` exposes a helper, e.g. `chapter.turns(tailer) -> list[Turn]`,
  that filters `tailer.ordered_turns()` down to the turns whose
  `prompt_id` is in `chapter.prompt_ids` (or a `section.prompt_ids` for a
  single section), preserving session order.
- `cli.py`'s existing `build_table(tailer, ..., detail=True)` renderer
  (built for `--detail`) already knows how to render a turn plus its
  nested `Unit` rows — it currently just iterates
  `tailer.ordered_turns()`. Reused as-is, but iterating the *filtered*
  turn list from the helper above instead of the full session. No
  duplicated rendering logic between the two commands.
- Net effect: `work-ledger chapters --detail` prints the chapter tree, and
  under each Section, the exact same turn/unit rows `--detail` alone would
  show for those turns — same columns, same Skill:/Subagent: labels, same
  costs. There is exactly one code path that renders a turn's units;
  `chapters --detail` just calls it with a scoped-down turn list.
- A further drill-down, `work-ledger chapters --only "<chapter title>"
  --detail`, filters to a single chapter (matched by exact title or a
  1-based index shown in the plain `chapters` output) — for going straight
  to "show me every call inside 'Fix double-counting bug'" without paging
  through the rest of the session.

## CLI surface

```
work-ledger chapters                            # chapter/section tree, cost rollup only
work-ledger chapters --detail                   # same tree, each section expands into its --detail rows
work-ledger chapters --only "<title|index>" --detail   # drill into one chapter's full detail
work-ledger chapters --transcript PATH          # for a specific transcript
work-ledger chapters --json                     # machine-readable output, for later cross-session tooling
```

Sample terminal output (illustrative, `--detail`):

```
Chapters — session 0daf9882... ($5.42 total, chaptering cost $0.0031)

▾ Build work-ledger v1 dashboard           $3.10  (61%)
    Read existing repo, scope decisions      $0.40
    Write transcript.py / pricing.py / cli.py $2.70

      [--detail rows for this section's turns, same as `work-ledger --detail`]
      22:10:16  How do we track how much...   26 calls   $1.87
          Bash                                              $0.25
          Read                                              $0.02
          ...

▾ Fix usage double-counting bug            $1.80  (33%)
    Diagnose duplicate message.id lines       $0.60
    Rewrite dedup logic, verify              $1.20
▾ Set up PR-review Routine                 $0.52  (10%)
```

Without `--detail`, output is just the chapter/section tree (first example
shown earlier in this doc) — cheap to read, no drill-down noise.

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
- **Local-model backend**: see `docs/local-model-chaptering-design.md` —
  a pluggable backend (e.g. Ollama) would keep session content off the
  network entirely, and removes the cost constraint that motivated the
  frozen-prefix caching decision below, opening up revisiting it.

## Open questions

1. Chapter granularity: should very short sessions (a handful of turns)
   always get one chapter, or should the model be told a minimum/maximum
   chapter count? Leaning toward no hard limit — let the model decide, and
   accept that very short sessions may just come back as a single chapter.
2. **Decided: linked, not separate.** `chapters --detail` drills down into
   the same per-unit rows `--detail` renders alone, scoped to each
   chapter/section's turns (see "Linking to `--detail`" under Architecture
   above). Called out explicitly by the repo owner as a key pain point —
   the value of chaptering is "here's what to cut," which requires seeing
   the actual calls behind an expensive chapter, not just its dollar
   total. Reuses `cli.py`'s existing turn/unit renderer against a filtered
   turn list; no separate rendering path to maintain.
3. **Decided: caching, frozen prefix.** Chaptering results are cached to
   disk (e.g. next to the transcript), keyed on transcript path + the set
   of `prompt_id`s chaptered so far. Cached chapter boundaries and titles
   are **frozen once written** — re-running `work-ledger chapters` on a
   session that has grown new turns since the last run only chapters the
   new turns (appending new chapters/sections, or extending the last one
   if the new turns are clearly its continuation), never revises or
   retitles a chapter that was already cached, and never re-pays for
   turns already chaptered. This accepts a known tradeoff: a chapter
   frozen early from a partial/ambiguous view of the session can't later
   be corrected once more turns reveal what it actually was — e.g. a
   chapter titled "Exploring X" might, with hindsight, obviously have been
   the first half of "Building Y," but the freeze means it stays
   "Exploring X." Chosen deliberately for now (simpler, cheaper, stable
   titles the user won't see change out from under them) with the
   explicit plan to revisit if that staleness turns out to matter in
   practice — see the Non-goals framing at the top: this is a first pass,
   not a final answer.

   **Scope note (issue #91):** the freeze applies to a real, paid
   chaptering decision — a response the backend actually returned,
   whether it fully covered the session, was refused, or only partially
   parsed. It does **not** apply when the backend call itself never
   produced a response at all (rejected/missing credentials, a network
   failure, a backend-unavailable error, or any other exception raised
   before a response came back). That case is a zero-cost infra failure,
   not a decision — freezing it would silently turn a transient outage
   (an expired key, a rate-limited burst across a large `--all` run) into
   a session permanently stuck as "Unsorted," with no signal and no way
   to retry short of hand-deleting its cache file. Those turns are left
   out of the cache entirely and retried on the next `chapters` run, for
   free, until a real response comes back.
