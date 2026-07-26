from work_ledger.chapters import UNSORTED_TITLE, Chapter, Section, _save_cache
from work_ledger.rollup import RollupCluster, build_rollup, normalize_title

from .conftest import assistant_lines, user_entry, write_jsonl


# --- normalize_title: the deterministic matching mechanism itself -------


def test_normalize_title_matches_the_issues_own_example():
    """The exact case the issue names: "Fix the double-counting bug" vs
    "fix double counting bug" - case, stopword ("the"), and hyphen-vs-
    space punctuation differences all collapse to the same key."""
    assert normalize_title("Fix the double-counting bug") == normalize_title(
        "fix double counting bug"
    )


def test_normalize_title_ignores_case_and_punctuation():
    assert normalize_title("Build the v1 Dashboard!") == normalize_title("build v1 dashboard")


def test_normalize_title_collapses_extra_whitespace():
    assert normalize_title("Fix   the    bug") == normalize_title("Fix the bug")


def test_normalize_title_strips_stopwords():
    assert normalize_title("Fix the bug in the login form") == normalize_title(
        "Fix bug login form"
    )


def test_normalize_title_light_plural_stemming():
    assert normalize_title("Fix the double-counting bugs") == normalize_title(
        "Fix the double-counting bug"
    )


def test_normalize_title_does_not_strip_double_s_endings():
    """A word ending in a double-s (e.g. "process") must not be
    depluralized into a different, wrong word - the stemmer only strips
    a single trailing 's' when the word doesn't already end in 'ss'."""
    assert normalize_title("Fix the process") == "fix process"


def test_normalize_title_stopwords_only_title_is_empty():
    assert normalize_title("The") == ""
    assert normalize_title("a the of") == ""


def test_normalize_title_does_not_merge_unrelated_titles():
    """False-positive guard: two titles that share structure but describe
    genuinely different work must not collapse to the same key."""
    assert normalize_title("Fix the login bug") != normalize_title("Fix the checkout bug")
    assert normalize_title("Build the v1 dashboard") != normalize_title("Build the v2 dashboard")


def test_normalize_title_known_false_negative_reworded_titles():
    """Documented, accepted limitation (see rollup.py's module docstring):
    a genuinely reworded title describing the same initiative in
    different words does NOT match - this is the tradeoff for staying
    deterministic/local instead of an LLM or embedding pass. If this ever
    turns out to hide real recurring cost in practice, that's the signal
    a v2 semantic matcher is worth designing."""
    assert normalize_title("Fix the double-counting bug") != normalize_title(
        "Resolve the cost overcounting issue"
    )


# --- build_rollup: clustering across synthetic sessions ------------------


def _write_session(path, prompt_id, cost_tokens=(1000, 200), model="claude-haiku-4-5", timestamp="2026-07-01T10:00:00Z"):
    entries = [
        user_entry(prompt_id, "do work", timestamp),
        *assistant_lines(
            f"m-{prompt_id}",
            model,
            {"input_tokens": cost_tokens[0], "output_tokens": cost_tokens[1]},
            [{"type": "text", "text": "done"}],
            timestamp,
        ),
    ]
    write_jsonl(path, entries)


def test_build_rollup_clusters_near_identical_titles_across_sessions(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_session(path_a, "p1", cost_tokens=(1000, 200))
    _write_session(path_b, "p2", cost_tokens=(2000, 400))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the double-counting bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="fix double counting bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    clusters = build_rollup([path_a, path_b])

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.num_sessions == 2
    assert cluster.num_chapters == 2
    assert sorted(cluster.sessions) == sorted([path_a.stem, path_b.stem])
    assert cluster.cost_usd > 0
    assert cluster.display_title == "Fix the double-counting bug"  # first-seen title kept


def test_build_rollup_keeps_unrelated_titles_in_separate_clusters(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_session(path_a, "p1")
    _write_session(path_b, "p2")

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the login bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="Build the v1 dashboard", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    clusters = build_rollup([path_a, path_b])

    assert len(clusters) == 2
    titles = {c.display_title for c in clusters}
    assert titles == {"Fix the login bug", "Build the v1 dashboard"}
    assert all(c.num_sessions == 1 for c in clusters)


def test_build_rollup_excludes_unsorted_fallback_chapters(tmp_path):
    """UNSORTED_TITLE chapters are chaptering's own fallback label, not a
    real initiative - two sessions' unrelated Unsorted chapters must not
    be clustered together as if they were the same recurring thing."""
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_session(path_a, "p1")
    _write_session(path_b, "p2")

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title=UNSORTED_TITLE, sections=[Section(title=UNSORTED_TITLE, prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title=UNSORTED_TITLE, sections=[Section(title=UNSORTED_TITLE, prompt_ids=["p2"])])],
    )

    clusters = build_rollup([path_a, path_b])

    assert clusters == []


def test_build_rollup_skips_sessions_without_cached_chapters(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_session(path_a, "p1")
    _write_session(path_b, "p2")
    # Only path_a gets a chapters cache; path_b has none at all.
    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )

    clusters = build_rollup([path_a, path_b])

    assert len(clusters) == 1
    assert clusters[0].num_sessions == 1
    assert clusters[0].sessions == [path_a.stem]


def test_build_rollup_sorts_by_cost_descending(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_session(path_a, "p1", cost_tokens=(500, 100))
    _write_session(path_b, "p2", cost_tokens=(50000, 10000))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Cheap initiative", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="Expensive initiative", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    clusters = build_rollup([path_a, path_b])

    assert [c.display_title for c in clusters] == ["Expensive initiative", "Cheap initiative"]
    assert clusters[0].cost_usd > clusters[1].cost_usd


def test_build_rollup_flags_unknown_model_cost(tmp_path):
    path = tmp_path / "session-a.jsonl"
    _write_session(path, "p1", model="totally-unknown-model")
    _save_cache(
        path,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Mystery model work", sections=[Section(title="s", prompt_ids=["p1"])])],
    )

    clusters = build_rollup([path])

    assert len(clusters) == 1
    assert clusters[0].unknown_model_cost is True
    assert clusters[0].cost_usd == 0.0


def test_build_rollup_empty_transcript_list():
    assert build_rollup([]) == []


def test_build_rollup_skips_chapter_whose_title_normalizes_to_empty(tmp_path):
    """A chapter title made entirely of stopwords (normalize_title returns
    "") must not become a bogus empty-string cluster."""
    path = tmp_path / "session-a.jsonl"
    _write_session(path, "p1")
    _save_cache(
        path,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="The", sections=[Section(title="s", prompt_ids=["p1"])])],
    )

    assert build_rollup([path]) == []


def test_rollup_cluster_num_sessions_property():
    cluster = RollupCluster(normalized_key="k", display_title="T", sessions=["a", "b", "a"])
    # sessions list is expected to already be deduped by build_rollup - the
    # property itself is a plain len(), not its own dedup pass.
    assert cluster.num_sessions == 3
