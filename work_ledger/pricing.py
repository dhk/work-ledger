"""Per-model Claude pricing and cost calculation from transcript usage blocks.

Rates are $/token (converted from $/MTok). Cache read/write use Anthropic's
standard multipliers off the base input rate: reads ~0.1x, 5-minute cache
writes ~1.25x, 1-hour cache writes ~2x. Sonnet 5 has introductory pricing
($2/$10 per MTok) through 2026-08-31 — not modeled here; this uses the
standard rate, so estimates run slightly high during the intro window.

The $3/$15 rate hardcoded below for "claude-sonnet-5" is Anthropic's
confirmed *standard* (post-intro) rate, verified against Anthropic's public
pricing pages while investigating #47 — it's not a guess at what the price
will become. Nothing here re-verifies that after 2026-08-31 passes, though:
see `SONNET_5_INTRO_PRICING_CUTOFF` and `tests/test_pricing.py`'s dated
forcing-function test, which starts failing once that date passes, so this
file gets an actual second look instead of a five-week-old assumption
quietly going stale forever.

A missing entry here is not a small gap: an unpriced model doesn't show a
wrong number, it shows no number, while every other column stays fully
populated. `claude-opus-5` was absent for weeks while it was the default
model, leaving ~99% of turns unpriced (issue #104) — the tool's whole
premise blank behind a UI that looked fine. Callers say *which* model was
unpriced (`unpriced_model_for`) rather than only that one was, so the next
missing entry names itself at the point of use.
"""

import re
from dataclasses import dataclass
from datetime import date


# See module docstring and #47: the day Sonnet 5's introductory pricing
# window ends - the RATES entry below already models the post-cutoff
# standard rate (confirmed, not guessed), but this constant exists so a
# dated test can force a re-check rather than trusting that confirmation
# forever.
SONNET_5_INTRO_PRICING_CUTOFF = date(2026, 8, 31)


@dataclass(frozen=True)
class ModelRate:
    input_per_mtok: float
    output_per_mtok: float
    # Whether this same rate covers the model's long-context variant id
    # (e.g. "claude-opus-5[1m]"). True only where the model's full context
    # window is served at standard pricing with no long-context premium -
    # see rate_for, which refuses to price a variant of anything else
    # rather than quietly billing it at the base rate.
    flat_long_context: bool = False


RATES: dict[str, ModelRate] = {
    "claude-opus-5": ModelRate(5.00, 25.00, flat_long_context=True),
    "claude-sonnet-5": ModelRate(3.00, 15.00, flat_long_context=True),
    "claude-opus-4-8": ModelRate(5.00, 25.00, flat_long_context=True),
    "claude-haiku-4-5": ModelRate(1.00, 5.00),
    "claude-fable-5": ModelRate(10.00, 50.00, flat_long_context=True),
    # Legacy/prior-generation models still seen in transcripts.
    "claude-sonnet-4-6": ModelRate(3.00, 15.00, flat_long_context=True),
    "claude-sonnet-4-5": ModelRate(3.00, 15.00),
    "claude-opus-4-7": ModelRate(5.00, 25.00, flat_long_context=True),
    "claude-opus-4-6": ModelRate(5.00, 25.00, flat_long_context=True),
    "claude-opus-4-5": ModelRate(5.00, 25.00),
    "claude-opus-4-1": ModelRate(5.00, 25.00),
    "claude-opus-4-0": ModelRate(5.00, 25.00),
    "claude-sonnet-4-0": ModelRate(3.00, 15.00),
}

# A trailing context-window variant marker on a model id, e.g. the "[1m]" in
# "claude-opus-5[1m]". Deliberately narrow: only a token-count marker counts
# as a context variant. A bracketed suffix meaning something else - "[fast]"
# would be the obvious one, since fast mode is priced well above the standard
# rate - must not be mistaken for one and silently billed as the base model.
_CONTEXT_VARIANT_RE = re.compile(r"^(?P<base>.+?)\[(?P<variant>\d+[kKmM])\]$")

CACHE_READ_MULT = 0.1
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0


def _base_rate_for(model: str) -> ModelRate | None:
    if model in RATES:
        return RATES[model]
    parts = model.split("-")
    if len(parts) > 1:
        return RATES.get("-".join(parts[:-1]))
    return None


def rate_for(model: str) -> ModelRate | None:
    """Look up rates for a model ID, stripping a trailing qualifier
    (a dated snapshot like "-20251001", or "-latest") if unknown as-is.

    A context-window variant id ("claude-opus-5[1m]") resolves to the base
    model's rate only when that model carries no long-context premium
    (`flat_long_context`). Where a premium exists - or where nobody has
    confirmed one doesn't - the variant stays deliberately unpriced and
    surfaces as "?", because billing 1M-context turns at the base rate
    would understate cost while looking exactly like a real figure. That's
    the failure mode this module exists to avoid (issue #104).
    """
    variant = _CONTEXT_VARIANT_RE.match(model)
    if variant is None:
        return _base_rate_for(model)
    rate = _base_rate_for(variant.group("base"))
    if rate is not None and rate.flat_long_context:
        return rate
    return None


def unpriced_model_label(model: str) -> str:
    """The name to show for a model that has no rate, so a "some models
    unpriced" note can say *which* one and the fix is a one-line table
    entry rather than an investigation (issue #104).

    Only for labeling an already-established miss - it doesn't itself
    decide whether a model is priced; ask `rate_for` for that.
    """
    return (model or "").strip() or "(no model id)"


def estimate_cost_usd(model: str, usage: dict) -> float | None:
    """Estimate cost from a transcript assistant message's `usage` block.

    Returns None if the model isn't in the pricing table (unknown/new model)
    rather than silently returning 0 - callers should show "?" not "$0.00".
    """
    rate = rate_for(model)
    if rate is None:
        return None

    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0

    cache_creation = usage.get("cache_creation") or {}
    write_5m = cache_creation.get("ephemeral_5m_input_tokens", 0) or 0
    write_1h = cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
    # Fallback when the detailed breakdown isn't present: treat the whole
    # cache_creation_input_tokens total as 5-minute writes (the common case).
    if not cache_creation and usage.get("cache_creation_input_tokens"):
        write_5m = usage.get("cache_creation_input_tokens", 0) or 0

    input_rate = rate.input_per_mtok / 1_000_000
    output_rate = rate.output_per_mtok / 1_000_000

    cost = (
        input_tokens * input_rate
        + output_tokens * output_rate
        + cache_read * input_rate * CACHE_READ_MULT
        + write_5m * input_rate * CACHE_WRITE_5M_MULT
        + write_1h * input_rate * CACHE_WRITE_1H_MULT
    )
    return cost
