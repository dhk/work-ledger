from pytest import approx

from work_ledger.pricing import CACHE_READ_MULT, CACHE_WRITE_5M_MULT, estimate_cost_usd, rate_for


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
