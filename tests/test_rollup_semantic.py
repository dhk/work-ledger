"""Tests for the optional #68 semantic-matching pass in isolation - the
Haiku call itself, its structured-output validation, and its env-var
trigger. See test_rollup.py for how `rollup.build_rollup_result` folds
this back into cluster membership, and test_waste.py for the
"waste --cross-session agrees with rollup" requirement.

The Anthropic call is mocked the same way test_chapters.py mocks
AnthropicBackend.call() - monkeypatching `anthropic.Anthropic` itself with
a fake client whose `.messages.parse(**kwargs)` returns a fake response -
never a real network call."""

import sys

import pytest

from work_ledger.rollup_semantic import (
    DETERMINISTIC_MATCHING,
    NO_CREDENTIALS_MESSAGE,
    ROLLUP_MATCHING_ENV_VAR,
    SEMANTIC_MATCHING,
    _MergeGroup,
    _MergesOut,
    _validate_groups,
    is_semantic_enabled,
    matching_mode,
    propose_merges,
)


# --- matching_mode / is_semantic_enabled ------------------------------------


def test_matching_mode_defaults_to_deterministic(monkeypatch):
    monkeypatch.delenv(ROLLUP_MATCHING_ENV_VAR, raising=False)
    assert matching_mode() == DETERMINISTIC_MATCHING
    assert is_semantic_enabled() is False


def test_matching_mode_semantic_enables(monkeypatch):
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")
    assert is_semantic_enabled() is True


def test_matching_mode_is_case_insensitive_and_stripped(monkeypatch):
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "  SEMANTIC  ")
    assert matching_mode() == SEMANTIC_MATCHING
    assert is_semantic_enabled() is True


def test_matching_mode_unknown_value_is_not_semantic(monkeypatch):
    """Any value other than exactly "semantic" behaves like the default -
    no separate error path, since this is an opt-in fire-and-forget
    setting, not a strict enum a typo should visibly break."""
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "yes-please")
    assert is_semantic_enabled() is False


# --- _validate_groups: never trust the model's output blindly --------------


def test_validate_groups_drops_unknown_titles():
    parsed = _MergesOut(groups=[_MergeGroup(titles=["Real title", "Invented title"])])
    cleaned = _validate_groups(parsed, ["Real title", "Other real title"])
    assert cleaned == []  # only one real title left after dropping the invented one


def test_validate_groups_keeps_valid_group_of_two():
    parsed = _MergesOut(groups=[_MergeGroup(titles=["A", "B"])])
    cleaned = _validate_groups(parsed, ["A", "B", "C"])
    assert cleaned == [["A", "B"]]


def test_validate_groups_drops_group_with_only_one_valid_title_left():
    parsed = _MergesOut(groups=[_MergeGroup(titles=["A", "Invented"])])
    cleaned = _validate_groups(parsed, ["A", "B"])
    assert cleaned == []


def test_validate_groups_a_title_belongs_to_at_most_one_group():
    parsed = _MergesOut(
        groups=[
            _MergeGroup(titles=["A", "B"]),
            _MergeGroup(titles=["B", "C"]),  # B already claimed by the first group
        ]
    )
    cleaned = _validate_groups(parsed, ["A", "B", "C"])
    assert cleaned == [["A", "B"]]  # second group drops to a single title ("C") and is dropped


def test_validate_groups_never_invents_titles_not_in_input():
    parsed = _MergesOut(groups=[_MergeGroup(titles=["Totally made up", "Also made up"])])
    cleaned = _validate_groups(parsed, ["Real one", "Real two"])
    assert cleaned == []


# --- propose_merges: success path -------------------------------------------


class _FakeUsage:
    def model_dump(self):
        return {"input_tokens": 100, "output_tokens": 50}


class _FakeParseResponse:
    def __init__(self, parsed=None, stop_reason="end_turn"):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.model = "claude-haiku-4-5"
        self.usage = _FakeUsage()


def _fake_response(parsed=None, stop_reason="end_turn"):
    return _FakeParseResponse(parsed=parsed, stop_reason=stop_reason)


def _install_fake_anthropic(monkeypatch, response=None, raise_exc=None):
    class _FakeMessages:
        def parse(self, **kwargs):
            if raise_exc is not None:
                raise raise_exc
            return response

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", lambda: _FakeClient())


def test_propose_merges_success_returns_validated_groups(monkeypatch):
    parsed = _MergesOut(groups=[_MergeGroup(titles=["Execute reading-list-builder daily flow", "Initialize reading list builder daily flow"])])
    _install_fake_anthropic(monkeypatch, response=_fake_response(parsed=parsed))

    result = propose_merges(["Execute reading-list-builder daily flow", "Initialize reading list builder daily flow", "Fix the login bug"])

    assert result.fallback_reason is None
    assert result.groups == [["Execute reading-list-builder daily flow", "Initialize reading list builder daily flow"]]
    assert result.cost_usd > 0


def test_propose_merges_fewer_than_two_titles_skips_the_call(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("must not call the model for fewer than 2 titles")

    monkeypatch.setattr("anthropic.Anthropic", boom)

    assert propose_merges([]).groups == []
    assert propose_merges(["Only one title"]).groups == []


def test_propose_merges_does_not_merge_unrelated_titles(monkeypatch):
    """The model correctly declining to group genuinely different work -
    an empty groups list, no fallback_reason (this isn't a failure)."""
    parsed = _MergesOut(groups=[])
    _install_fake_anthropic(monkeypatch, response=_fake_response(parsed=parsed))

    result = propose_merges(["Fix the login bug", "Fix the checkout bug"])

    assert result.groups == []
    assert result.fallback_reason is None


# --- propose_merges: every failure mode degrades gracefully ----------------


def test_propose_merges_no_credentials_falls_back(monkeypatch):
    def no_key(**kwargs):
        raise TypeError(
            '"Could not resolve authentication method. Expected one of api_key, auth_token, '
            'or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` '
            'headers to be explicitly omitted"'
        )

    class _FakeMessages:
        def parse(self, **kwargs):
            no_key(**kwargs)

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", lambda: _FakeClient())

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert result.fallback_reason == NO_CREDENTIALS_MESSAGE


def test_propose_merges_unrelated_type_error_falls_back_generically(monkeypatch):
    class _FakeMessages:
        def parse(self, **kwargs):
            raise TypeError("unexpected keyword argument 'foo'")

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", lambda: _FakeClient())

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert "No ANTHROPIC_API_KEY" not in result.fallback_reason
    assert "semantic matching call failed" in result.fallback_reason


def test_propose_merges_invalid_api_key_falls_back(monkeypatch):
    import anthropic
    import httpx

    class _FakeMessages:
        def parse(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            response = httpx.Response(status_code=401, request=request)
            raise anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", lambda: _FakeClient())

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert "rejected by the server" in result.fallback_reason


def test_propose_merges_refusal_falls_back(monkeypatch):
    _install_fake_anthropic(monkeypatch, response=_fake_response(parsed=None, stop_reason="refusal"))

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert "refused" in result.fallback_reason


def test_propose_merges_malformed_response_falls_back(monkeypatch):
    """parsed_output=None with a non-refusal stop_reason (schema mismatch,
    truncation, etc.) - distinguishable fallback wording, mirroring
    chapters.get_chapters's own malformed-shape handling."""
    _install_fake_anthropic(monkeypatch, response=_fake_response(parsed=None, stop_reason="max_tokens"))

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert "didn't match the expected shape" in result.fallback_reason


def test_propose_merges_generic_exception_falls_back(monkeypatch):
    class _FakeMessages:
        def parse(self, **kwargs):
            raise RuntimeError("network error")

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", lambda: _FakeClient())

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert "semantic matching call failed" in result.fallback_reason


def test_propose_merges_never_raises_on_any_failure(monkeypatch):
    """Belt-and-suspenders: whatever exception type the SDK throws,
    propose_merges must return a result, never propagate."""

    class _FakeMessages:
        def parse(self, **kwargs):
            raise ValueError("something totally unexpected")

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", lambda: _FakeClient())

    try:
        result = propose_merges(["A", "B"])
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"propose_merges must never raise, got {e!r}")
    assert result.fallback_reason is not None


def test_propose_merges_degrades_when_anthropic_fails_to_import(monkeypatch):
    """Issue #99: a broken/incomplete environment (missing or mismatched
    anthropic install) must degrade the same as any other failure mode
    this function already handles, not crash before ever reaching the
    try/except below - which can't even be entered if the import itself
    is what failed, since its except clauses reference
    anthropic.AuthenticationError etc."""
    monkeypatch.setitem(sys.modules, "anthropic", None)  # forces `import anthropic` to raise ImportError

    result = propose_merges(["A", "B"])
    assert result.groups == []
    assert "failed to import" in result.fallback_reason
