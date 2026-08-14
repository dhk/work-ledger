from datetime import date

from pytest import approx

from work_ledger.pricing import (
    CACHE_READ_MULT,
    CACHE_WRITE_5M_MULT,
    RATES,
    SONNET_5_INTRO_PRICING_CUTOFF,
    estimate_cost_usd,
    rate_for,
    unpriced_model_label,
)


def test_rate_for_known_model():
    assert rate_for("claude-haiku-4-5") is not None


def test_rate_for_unknown_model_returns_none():
    assert rate_for("some-model-nobody-has-heard-of") is None


def test_rate_for_no_dash_unknown_model_returns_none():
    assert rate_for("unknown") is None


def test_rate_for_strips_dated_snapshot_suffix():
    # Regression test: rate_for used to only strip a trailing suffix when
    # its last character wasn't a digit, so a real dated snapshot id like
    # this (all-digit suffix) fell through to None instead of matching the
    # base model - found while writing this test suite.
    assert rate_for("claude-haiku-4-5-20251001") == rate_for("claude-haiku-4-5")


def test_rate_for_strips_latest_suffix():
    assert rate_for("claude-haiku-4-5-latest") == rate_for("claude-haiku-4-5")


def test_rate_for_opus_5_is_priced():
    """Regression test for #104: `claude-opus-5` was missing from RATES
    while it was the default model, so ~99% of turns on a current machine
    showed "?" for cost - the tool's whole premise blank behind a UI that
    otherwise looked fully populated."""
    rate = rate_for("claude-opus-5")
    assert rate is not None
    assert rate.input_per_mtok == 5.00
    assert rate.output_per_mtok == 25.00


def test_rate_for_context_variant_resolves_when_no_long_context_premium():
    """"claude-opus-5[1m]" prices at the base rate because Opus 5 serves
    its full context window at standard pricing."""
    assert rate_for("claude-opus-5[1m]") == rate_for("claude-opus-5")


def test_rate_for_context_variant_unpriced_without_a_confirmed_flat_rate():
    """The opposite case, and the reason this isn't just a strip-the-suffix
    fallback: where a long-context premium exists (or nobody has confirmed
    one doesn't), the variant stays unpriced and shows "?" rather than
    billing at the base rate, which would understate cost while looking
    exactly like a real figure."""
    assert rate_for("claude-sonnet-4-5") is not None
    assert rate_for("claude-sonnet-4-5[1m]") is None


def test_rate_for_non_context_bracket_suffix_is_never_priced():
    """Only a token-count marker counts as a context variant. A bracketed
    suffix meaning something else - "[fast]" being the obvious one, since
    fast mode is priced well above the standard rate - must not resolve to
    the base model's rate."""
    assert rate_for("claude-opus-5[fast]") is None


def test_rate_for_context_variant_of_dated_snapshot():
    """The two suffix rules compose: strip the bracketed variant, then the
    dated-snapshot suffix underneath it."""
    assert rate_for("claude-opus-5-20260101[1m]") == rate_for("claude-opus-5")


def test_unpriced_model_label_falls_back_for_a_missing_id():
    assert unpriced_model_label("claude-opus-9") == "claude-opus-9"
    assert unpriced_model_label("") == "(no model id)"
    assert unpriced_model_label(None) == "(no model id)"


def test_estimate_cost_opus_5_prices_a_real_usage_block():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert estimate_cost_usd("claude-opus-5", usage) == approx(30.00)


def test_estimate_cost_unknown_model_returns_none_not_zero():
    # Callers rely on None (not 0) to show "?" instead of silently
    # under-reporting cost for a model this tool doesn't have rates for.
    assert estimate_cost_usd("totally-unknown-model", {"input_tokens": 100, "output_tokens": 50}) is None


def test_estimate_cost_basic_input_output():
    rate = rate_for("claude-haiku-4-5")
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    cost = estimate_cost_usd("claude-haiku-4-5", usage)
    assert cost == approx(rate.input_per_mtok + rate.output_per_mtok)


def test_estimate_cost_cache_read_uses_discount_multiplier():
    rate = rate_for("claude-haiku-4-5")
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000}
    cost = estimate_cost_usd("claude-haiku-4-5", usage)
    assert cost == approx(rate.input_per_mtok * CACHE_READ_MULT)


def test_estimate_cost_cache_creation_breakdown():
    rate = rate_for("claude-haiku-4-5")
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 0},
    }
    cost = estimate_cost_usd("claude-haiku-4-5", usage)
    assert cost == approx(rate.input_per_mtok * CACHE_WRITE_5M_MULT)


def test_estimate_cost_cache_creation_flat_fallback():
    """Without the detailed cache_creation breakdown, the flat
    cache_creation_input_tokens total is treated as 5-minute writes."""
    rate = rate_for("claude-haiku-4-5")
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    cost = estimate_cost_usd("claude-haiku-4-5", usage)
    assert cost == approx(rate.input_per_mtok * CACHE_WRITE_5M_MULT)


def test_sonnet_5_intro_pricing_cutoff_forces_a_revisit():
    """Forcing function for #47: `claude-sonnet-5`'s $3/$15 RATES entry is
    Anthropic's confirmed *standard* rate (verified against Anthropic's
    public pricing pages while investigating #47), already correct for
    after the introductory-pricing window ($2/$10 per MTok) ends on
    SONNET_5_INTRO_PRICING_CUTOFF (2026-08-31) - not modeled here, so
    estimates run slightly high during that ~5-week window, an accepted
    tradeoff per #47's own open questions.

    This test starts failing the day that cutoff passes - not because the
    rate is expected to be wrong, but so CI actually forces someone to
    open pricing.py and re-confirm the rate (pricing can change again)
    rather than an old assumption staying silently unverified forever.
    If you're reading this because it just failed: re-check Anthropic's
    current published Sonnet 5 rate, update RATES/this cutoff/this
    docstring as needed, then move the cutoff forward or delete this test
    once it's no longer needed as a forcing function.
    """
    assert date.today() <= SONNET_5_INTRO_PRICING_CUTOFF, (
        "Sonnet 5's introductory-pricing window has ended - re-verify "
        "work_ledger/pricing.py's claude-sonnet-5 rate against Anthropic's "
        "current published pricing before updating/removing this test."
    )
    assert RATES["claude-sonnet-5"].input_per_mtok == 3.00
    assert RATES["claude-sonnet-5"].output_per_mtok == 15.00
