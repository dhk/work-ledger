import pytest

from work_ledger.references import (
    clean_synopsis,
    extract_pr_refs,
    extract_ticket_refs,
    pr_url,
    ticket_url,
)


# --- extract_ticket_refs ----------------------------------------------


def test_extract_ticket_refs_finds_jira_style_ids():
    assert extract_ticket_refs("fix SLA-42 and also look at ABBV-1001") == ["SLA-42", "ABBV-1001"]


def test_extract_ticket_refs_dedupes_preserving_first_seen_order():
    assert extract_ticket_refs("SLA-42 again, SLA-42, then SLA-43") == ["SLA-42", "SLA-43"]


def test_extract_ticket_refs_no_matches_returns_empty():
    assert extract_ticket_refs("just a plain sentence") == []


def test_extract_ticket_refs_empty_text_returns_empty():
    assert extract_ticket_refs("") == []


@pytest.mark.parametrize("text", ["encode as UTF-8", "supports ISO-8601", "compare to GPT-4", "use HTTP-2"])
def test_extract_ticket_refs_generic_mode_filters_stoplist_false_positives(text):
    """Without WORK_LEDGER_TICKET_PREFIX set, common non-ticket prefixes
    (encoding/standard/model names) must not be reported as tickets -
    the whole reason the stoplist exists."""
    assert extract_ticket_refs(text) == []


def test_extract_ticket_refs_configured_prefix_is_exact_and_excludes_others(monkeypatch):
    monkeypatch.setenv("WORK_LEDGER_TICKET_PREFIX", "SLA,ABBV")
    text = "SLA-42 and RANDOM-99 and ABBV-7"
    assert extract_ticket_refs(text) == ["SLA-42", "ABBV-7"]


def test_extract_ticket_refs_configured_prefix_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("WORK_LEDGER_TICKET_PREFIX", "sla")
    assert extract_ticket_refs("SLA-42") == ["SLA-42"]


def test_extract_ticket_refs_configured_prefix_allows_stoplist_prefix_through(monkeypatch):
    """A configured prefix is exact-match, not filtered by the generic
    stoplist - if your org's real prefix happens to collide with a
    stoplist entry, explicit configuration must win."""
    monkeypatch.setenv("WORK_LEDGER_TICKET_PREFIX", "API")
    assert extract_ticket_refs("see API-100 for details") == ["API-100"]


# --- extract_pr_refs -----------------------------------------------------


def test_extract_pr_refs_finds_hash_numbers():
    assert extract_pr_refs("fixed in #85, follow-up in #86") == ["85", "86"]


def test_extract_pr_refs_dedupes_preserving_order():
    assert extract_pr_refs("#85 again #85 then #86") == ["85", "86"]


def test_extract_pr_refs_no_matches_returns_empty():
    assert extract_pr_refs("no references here") == []


def test_extract_pr_refs_does_not_match_word_char_immediately_before_hash():
    """"issue123#" shouldn't be treated as a fresh reference at the wrong
    boundary - the (?<![\\w/#]) lookbehind exists for exactly this."""
    assert extract_pr_refs("see issue123#456") == []


# --- ticket_url / pr_url --------------------------------------------------


def test_ticket_url_unset_returns_none():
    assert ticket_url("SLA-42") is None


def test_ticket_url_uses_configured_template(monkeypatch):
    monkeypatch.setenv("WORK_LEDGER_TICKET_URL_TEMPLATE", "https://yourorg.atlassian.net/browse/{id}")
    assert ticket_url("SLA-42") == "https://yourorg.atlassian.net/browse/SLA-42"


def test_pr_url_unset_returns_none():
    assert pr_url("85") is None


def test_pr_url_uses_configured_repo_and_issues_path(monkeypatch):
    """/issues/<n> deliberately, not /pull/<n> - GitHub resolves that
    correctly whether <n> is actually an issue or a PR, which /pull/<n>
    alone would not for a plain issue."""
    monkeypatch.setenv("WORK_LEDGER_GITHUB_REPO", "dhk/work-ledger")
    assert pr_url("85") == "https://github.com/dhk/work-ledger/issues/85"


# --- clean_synopsis --------------------------------------------------------


def test_clean_synopsis_strips_leading_filler_word():
    assert clean_synopsis("ok, let's focus on SLA reporting") == "Let's focus on SLA reporting"


def test_clean_synopsis_collapses_whitespace():
    assert clean_synopsis("fix   the\n\nbug") == "fix the bug"


def test_clean_synopsis_no_filler_prefix_unchanged_besides_whitespace():
    assert clean_synopsis("search confluence for X") == "search confluence for X"


def test_clean_synopsis_truncates_at_word_boundary():
    text = "a" * 40 + " " + "b" * 40  # 81 chars total, well past max_len
    result = clean_synopsis(text, max_len=40)
    assert result.endswith("…")
    assert not result[:-1].endswith(" ")  # trimmed cleanly, no trailing space before the ellipsis
    assert len(result) <= 41


def test_clean_synopsis_short_text_untouched_besides_cleanup():
    assert clean_synopsis("short") == "short"


def test_clean_synopsis_empty_string_returns_empty():
    assert clean_synopsis("") == ""
