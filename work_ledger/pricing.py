"""Per-model Claude pricing and cost calculation from transcript usage blocks.

Rates are $/token (converted from $/MTok). Cache read/write use Anthropic's
standard multipliers off the base input rate: reads ~0.1x, 5-minute cache
writes ~1.25x, 1-hour cache writes ~2x. Sonnet 5 has introductory pricing
($2/$10 per MTok) through 2026-08-31 — not modeled here; this uses the
standard rate, so estimates run slightly high during the intro window.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRate:
    input_per_mtok: float
    output_per_mtok: float


RATES: dict[str, ModelRate] = {
    "claude-sonnet-5": ModelRate(3.00, 15.00),
    "claude-opus-4-8": ModelRate(5.00, 25.00),
    "claude-haiku-4-5": ModelRate(1.00, 5.00),
    "claude-fable-5": ModelRate(10.00, 50.00),
    # Legacy/prior-generation models still seen in transcripts.
    "claude-sonnet-4-6": ModelRate(3.00, 15.00),
    "claude-sonnet-4-5": ModelRate(3.00, 15.00),
    "claude-opus-4-7": ModelRate(5.00, 25.00),
    "claude-opus-4-6": ModelRate(5.00, 25.00),
    "claude-opus-4-5": ModelRate(5.00, 25.00),
    "claude-opus-4-1": ModelRate(5.00, 25.00),
    "claude-opus-4-0": ModelRate(5.00, 25.00),
    "claude-sonnet-4-0": ModelRate(3.00, 15.00),
}

CACHE_READ_MULT = 0.1
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0


def rate_for(model: str) -> ModelRate | None:
    """Look up rates for a model ID, stripping any date suffix if unknown as-is."""
    if model in RATES:
        return RATES[model]
    base = "-".join(model.split("-")[:-1]) if model[-1:].isdigit() is False else model
    return RATES.get(base)


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
