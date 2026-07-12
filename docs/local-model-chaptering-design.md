# Design: Pluggable Chaptering Backend (Local Models)

Status: proposed, not yet built.
Author: written by Claude, from a design conversation with the repo owner.
Related: `docs/session-chaptering-design.md` (the chaptering feature this
extends - read that first), `work_ledger/chapters.py`, PR #14 (chapter
`category` taxonomy - assumed to already exist).

## Problem

`chapters` today hard-codes a single backend: the hosted Anthropic API
(`anthropic.Anthropic()`, model Haiku 4.5). Three consequences of that:

1. Every chaptering pass sends real session content off-machine - prompt
   snippets and unit labels leave the user's machine for Anthropic's API.
   This is the one place in work-ledger's local-transcript-first design
   where that's true; everything else never leaves disk.
2. It requires its own Anthropic credentials, separate from the user's
   Claude Code session/subscription.
3. Because each call is billed, `chapters.py`'s caching was deliberately
   designed to freeze once written (see session-chaptering-design.md's
   "Decided: caching, frozen prefix") specifically to avoid re-paying for
   turns already chaptered. That decision knowingly accepted a staleness
   tradeoff: a chapter titled early from partial context can't later be
   corrected once more turns clarify what it actually was.

A local-model backend removes the cost constraint that motivated freezing
in the first place. That's not a side benefit - it's the headline reason
to build this: it makes it possible to actually revisit "Decided: caching,
frozen prefix" and fix the staleness gap that doc already flagged as
known and deliberately accepted, not fixed.

## Goals

- Let `chapters` run entirely offline: session content never leaves the
  machine when using a local backend.
- Preserve the single most important property of the existing
  implementation - enforced structured output, not a prompted "return
  JSON" convention - even for a local model.
- Make freeze/unfreeze a backend-aware policy, not one hardcoded choice:
  a local backend can afford to re-chapter cheaply; a hosted backend
  still shouldn't re-pay for old turns by default.
- Zero regression for existing users: default backend stays
  Anthropic/Haiku, existing `<session>.chapters.json` cache files stay
  valid.

## Non-goals (for this pass)

- OpenAI/Gemini hosted backends. A related but separate question raised
  earlier and not yet designed; this doc is scoped to local inference,
  though the backend abstraction below is written so a hosted alternative
  could reuse it later without a second redesign.
- Fine-tuning or bundling a purpose-built small model. Assume an
  off-the-shelf local model (Qwen 2.5, Llama 3.1, etc.) run by an existing
  local-inference server - work-ledger doesn't train or ship a model.
- Automatic backend selection or fallback (e.g. "try local, fall back to
  hosted"). Explicit user configuration only, at least at first.

## Why not pure heuristics

Not re-litigated here - see session-chaptering-design.md's own "Why not
pure heuristics" section; nothing about running the same task on a
different model changes that reasoning.

## Architecture

Introduce a small backend abstraction and extract today's Anthropic call
behind it, unchanged:

```python
class ChapterBackend(Protocol):
    def call(self, outline: str, prior_chapter_titles: list[str]) -> BackendResponse: ...

@dataclass
class BackendResponse:
    parsed: _ChaptersOut | None
    stop_reason: str
    cost_usd: float          # always 0.0 for a local backend
    wall_clock_s: float      # new - see "Latency implications" below
```

- `AnthropicBackend` - today's `_call_model` body, moved as-is.
- `OllamaBackend` - new (below).

`_call_model` becomes a thin dispatcher: pick a backend from config, call
it, return its `BackendResponse`. Everything downstream (`_validate_partition`,
the Unsorted fallback, cache read/write) is backend-agnostic and doesn't
change.

### OllamaBackend specifics

- Talks to a local Ollama server (default `http://localhost:11434`), via
  the `ollama` PyPI package or a plain HTTP POST to `/api/chat`. Would be
  a new optional dependency, same pattern as `report`'s `playwright`
  extra in `pyproject.toml` (e.g. `local-chapters = ["ollama>=0.4"]`).
- **Structured output**: Ollama's `/api/chat` accepts a `format` field
  that takes a JSON schema (not just the string `"json"`) and constrains
  decoding to match it - the local equivalent of the Anthropic SDK's
  `output_format=`. We'd pass `_ChaptersOut.model_json_schema()` and parse
  the guaranteed-valid JSON ourselves (no `.parse()` convenience method
  like the Anthropic SDK provides, but the validity guarantee is the same
  in spirit - this is the detail that makes local chaptering acceptable
  at all, not a downgrade to a prompted convention).
- **Cost**: always `$0.0` - no rates lookup needed, `pricing.py` doesn't
  need a new entry. Still worth surfacing *something* in the UI in place
  of cost, since a local pass isn't actually free of overhead - wall-clock
  time is the real cost now (e.g. "chaptering this session took 47s
  locally" instead of "cost $0.0031").
- **Model choice**: no default recommendation baked into the code. Model
  suitability depends on the user's hardware; document a couple of
  known-reasonable starting points in the README rather than picking one
  authoritatively, and expect this list to need real testing against
  actual sessions before it's trustworthy (see Open Questions).

### Reliability implications (the real tradeoff)

A smaller local model is meaningfully more likely to violate the
partition constraint (drop or duplicate `prompt_id`s) than Haiku 4.5.
`_validate_partition` and the Unsorted fallback already handle this
without any code change - but expect the practical effect to shift:

- Unsorted should be expected as a routine, regular outcome on some local
  models, not the rare edge case it is today with Haiku.
- If that turns out to be genuinely annoying in practice, a fallback-rate
  indicator (e.g. "3 of 12 chapters this session fell back to Unsorted")
  would be a reasonable follow-up - not designed here, flagged as likely
  future work once there's real usage to look at.

### Latency implications

`MAX_TOKENS=16000` was chosen as "the safe non-streaming ceiling" for the
hosted API. Generating that much output locally on modest hardware could
take minutes, not seconds. Two options, not mutually exclusive:

- Give `OllamaBackend` its own (lower) max-tokens ceiling, accepting more
  frequent Unsorted fallback on long sessions in exchange for a bounded
  wait.
- Add streaming to `OllamaBackend` specifically (Ollama supports it
  naturally) so a long local pass shows progress instead of appearing
  hung. The hosted path stays non-streaming, as today - this is purely a
  local-backend concern.

## Unfreezing chapters (the actual point of this doc)

Today: chapter/section assignments are frozen forever once written; a
re-run only chapters newly-arrived turns and never revisits earlier ones
(see session-chaptering-design.md, "Decided: caching, frozen prefix").
That was chosen specifically to avoid re-paying the hosted API for turns
already chaptered.

A local backend has no per-call cost, so that specific justification
disappears - re-chaptering the *entire* session from scratch on every run
becomes something we could do "for free," modulo wall-clock time. That
doesn't mean we should unfreeze unconditionally, though: there's a second
reason freezing existed that a local model doesn't remove - chapter
*identity* stability across runs (`--only "<title>"` matching, a user's
mental model of "chapter 3 is the caching chapter" not shifting under
them). Three concrete policy options:

**Option A: Full re-chapter every run (no freezing) for local backends.**
Every `chapters` call sends the entire turn outline - not just new turns -
and takes whatever grouping comes back, discarding the old cache.
Simplest to reason about, and actually fixes staleness. Cost: chapter
identity (title, count, `--only` matching) can change between runs - a
workflow or script built around "chapter 3" could silently break. Also the
slowest option, since it always re-chapters everything, not just what's
new.

**Option B: Sliding re-chapter window.**
Keep today's "append new turns" behavior for everything except the last K
chapters (or last N turns), which get re-sent alongside new turns and are
allowed to be revised, merged, or retitled. Chapters older than the
window stay frozen. This targets the actual failure mode the original doc
calls out ("Exploring X" that should've become "Building Y" once more
turns arrived) without re-litigating the whole session's history on every
run. Needs a concrete choice of K/N, and a decision about what happens to
a chapter that falls out of the window mid-revision.

**Option C: Freeze on session inactivity, not on write.**
Treat the cache as fully revisable while a session is "live" (new turns
still arriving recently) and hard-freeze only once a session goes cold
(no new turns for some duration, or the transcript is no longer the
active one). This maps freezing to "the session is actually done" rather
than "we already spent money on it" - arguably what should have driven
the decision even before cost forced an early, conservative version of it.

**Recommendation (not a decision - see Open Questions): start with Option
C for local backends.** It directly targets the staleness case the
original doc flagged, without Option A's "identity can change on every
single re-run" instability, and without inventing a new tunable window
(K/N) up front the way Option B does. The hosted (Anthropic) backend keeps
today's frozen-prefix-forever behavior unchanged by default, since the
cost reason for it still applies there.

## Config surface (sketch)

Mirrors the existing `ANTHROPIC_API_KEY` / `ant auth login` precedent -
environment variables, not new required CLI flags, since backend choice
is a one-time setup decision, not a per-invocation one:

```
WORK_LEDGER_CHAPTER_BACKEND=ollama        # default: anthropic
WORK_LEDGER_CHAPTER_MODEL=qwen2.5:14b     # backend-specific model name
OLLAMA_HOST=http://localhost:11434        # default if unset

work-ledger chapters                      # uses the configured backend transparently
```

## Migration / compatibility

- Existing `<session>.chapters.json` cache files remain valid regardless
  of which backend/freeze policy is chosen - same "default missing field
  to a safe value" precedent already used for `category` (PR #14) applies
  to whatever new fields an unfreeze policy needs (e.g. a per-chapter
  frozen flag or last-seen-turn timestamp for Option C).
- Default backend and default freeze policy are unchanged from today;
  none of this is opt-out, all of it is explicit opt-in configuration.

## Open questions

1. **Which unfreeze policy (A/B/C above)?** Recommendation is C, not a
   decision - needs the repo owner's call before implementation, since it
   changes chapter identity stability, a thing an earlier decision
   explicitly protected.
2. Does the cache format need a `frozen: bool` per chapter, or a
   `last_seen_turn_at` timestamp, to support Option C? Implementation
   detail, deferred until question 1 is settled.
3. If chapters become revisable (B or C), should `--only "<title>"`
   matching get a stable id fallback instead of relying on title
   substring/index matching, which assumes titles don't change? Not
   needed under today's fully-frozen behavior or under a
   never-unfrozen hosted backend.
4. What's the actual quality gap, in practice, between Haiku 4.5 and a
   realistic local choice (e.g. Qwen 2.5 14B) on this specific
   partition+title+category task? Untested - want to eyeball real output
   on a real session before committing to any specific recommended-model
   list in the README.
5. OpenAI/Gemini hosted backends are out of scope here, but the
   `ChapterBackend` shape above should be sanity-checked against that
   future need before it's finalized, so it isn't redesigned twice.
