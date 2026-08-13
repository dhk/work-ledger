import pytest

from work_ledger.chapters import UNSORTED_TITLE, Chapter, Section, _save_cache
from work_ledger.rollup import (
    RollupCluster,
    build_rollup,
    build_rollup_result,
    collapse_to_other,
    fold_below_cost,
    is_other_cluster,
    normalize_title,
    top_n_clusters,
    with_cumulative,
)
from work_ledger.rollup_semantic import ROLLUP_MATCHING_ENV_VAR, SemanticMergeResult

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


# --- build_rollup_result: the optional #68 semantic pass -------------------
#
# rollup_semantic.propose_merges is mocked directly here (rather than the
# Anthropic SDK) - test_rollup_semantic.py already covers propose_merges's
# own mocked-Anthropic-call behavior and failure handling in isolation;
# these tests are about whether build_rollup_result folds a given
# SemanticMergeResult back into cluster membership correctly.


def _make_singleton(tmp_path, name, prompt_id, title, cost_tokens=(1000, 200)):
    path = tmp_path / f"{name}.jsonl"
    _write_session(path, prompt_id, cost_tokens=cost_tokens)
    _save_cache(
        path,
        chaptered_ids=[prompt_id],
        chapters=[Chapter(title=title, sections=[Section(title="s", prompt_ids=[prompt_id])])],
    )
    return path


def test_build_rollup_result_default_mode_is_deterministic_only(tmp_path, monkeypatch):
    """Env var unset (the default) - build_rollup_result must not even call
    propose_merges, and its clusters must be identical to plain
    build_rollup's (byte-for-byte unchanged default behavior)."""
    monkeypatch.delenv(ROLLUP_MATCHING_ENV_VAR, raising=False)

    def boom(titles):
        raise AssertionError("propose_merges must not be called when matching mode is deterministic")

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", boom)

    path_a = _make_singleton(tmp_path, "a", "p1", "Execute reading-list-builder daily flow")
    path_b = _make_singleton(tmp_path, "b", "p2", "Initialize reading list builder daily flow")

    result = build_rollup_result([path_a, path_b])
    plain = build_rollup([path_a, path_b])

    assert result.clusters == plain
    assert len(result.clusters) == 2  # genuinely different normalized keys - stay singletons
    assert result.semantic_merges == []
    assert result.semantic_fallback_reason is None
    assert result.key_map == {}


def test_build_rollup_result_semantic_merges_singleton_titles(tmp_path, monkeypatch):
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")

    path_a = _make_singleton(tmp_path, "a", "p1", "Execute reading-list-builder daily flow", cost_tokens=(1000, 200))
    path_b = _make_singleton(tmp_path, "b", "p2", "Initialize reading list builder daily flow", cost_tokens=(2000, 400))
    path_c = _make_singleton(tmp_path, "c", "p3", "Fix the login bug", cost_tokens=(500, 100))

    def fake_propose_merges(titles):
        assert set(titles) == {
            "Execute reading-list-builder daily flow",
            "Initialize reading list builder daily flow",
            "Fix the login bug",
        }
        return SemanticMergeResult(
            groups=[["Execute reading-list-builder daily flow", "Initialize reading list builder daily flow"]]
        )

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", fake_propose_merges)

    result = build_rollup_result([path_a, path_b, path_c])

    assert result.semantic_fallback_reason is None
    assert len(result.semantic_merges) == 1
    merge = result.semantic_merges[0]
    assert merge.titles == [
        "Execute reading-list-builder daily flow",
        "Initialize reading list builder daily flow",
    ]
    assert merge.merged_title == "Execute reading-list-builder daily flow"  # first-seen title kept

    # Two singleton clusters folded into one; the unrelated one stays separate.
    assert len(result.clusters) == 2
    merged_cluster = next(c for c in result.clusters if c.display_title == "Execute reading-list-builder daily flow")
    assert merged_cluster.num_sessions == 2
    assert sorted(merged_cluster.sessions) == sorted([path_a.stem, path_b.stem])
    assert merged_cluster.num_chapters == 2
    assert merged_cluster.cost_usd > 0

    unrelated_cluster = next(c for c in result.clusters if c.display_title == "Fix the login bug")
    assert unrelated_cluster.num_sessions == 1

    # key_map lets waste.py agree with this same clustering.
    key_a = normalize_title("Execute reading-list-builder daily flow")
    key_b = normalize_title("Initialize reading list builder daily flow")
    assert result.key_map[key_a] == key_a  # primary (first-seen) key maps to itself
    assert result.key_map[key_b] == key_a


def test_build_rollup_result_semantic_does_not_merge_unrelated_titles(tmp_path, monkeypatch):
    """The model declining to merge (empty groups) is not a failure - no
    fallback_reason, clusters unchanged from the deterministic pass."""
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")

    path_a = _make_singleton(tmp_path, "a", "p1", "Fix the login bug")
    path_b = _make_singleton(tmp_path, "b", "p2", "Fix the checkout bug")

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges", lambda titles: SemanticMergeResult(groups=[])
    )

    result = build_rollup_result([path_a, path_b])

    assert len(result.clusters) == 2
    assert result.semantic_merges == []
    assert result.semantic_fallback_reason is None


def test_build_rollup_result_semantic_failure_falls_back_to_deterministic(tmp_path, monkeypatch):
    """A degraded semantic pass (no credentials, refusal, etc. - already
    covered in isolation by test_rollup_semantic.py) must still leave
    build_rollup_result returning the deterministic clustering, plus a
    distinguishable fallback_reason - never a crash, never silently
    identical to "nothing new to merge"."""
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")

    path_a = _make_singleton(tmp_path, "a", "p1", "Fix the login bug")
    path_b = _make_singleton(tmp_path, "b", "p2", "Fix the checkout bug")

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges",
        lambda titles: SemanticMergeResult(groups=[], fallback_reason="semantic matching call failed (boom)"),
    )

    result = build_rollup_result([path_a, path_b])

    assert len(result.clusters) == 2  # deterministic-only result, untouched
    assert result.semantic_merges == []
    assert result.semantic_fallback_reason == "semantic matching call failed (boom)"


def test_build_rollup_result_skips_semantic_call_with_fewer_than_two_singletons(tmp_path, monkeypatch):
    """Nothing to batch a call for when there's at most one singleton -
    propose_merges must not even be called (no pointless $0 API call)."""
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")

    path_a = _make_singleton(tmp_path, "a", "p1", "The only initiative")

    def boom(titles):
        raise AssertionError("propose_merges must not be called with fewer than 2 singleton titles")

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", boom)

    result = build_rollup_result([path_a])
    assert len(result.clusters) == 1
    assert result.semantic_merges == []


def test_build_rollup_result_semantic_pass_ignores_already_multi_session_clusters(tmp_path, monkeypatch):
    """A cluster that already spans 2+ sessions via deterministic matching
    is not a singleton and must not be fed into the semantic batch, even
    if its title superficially resembles a real singleton's."""
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")

    path_a = _make_singleton(tmp_path, "a", "p1", "Fix the double-counting bug")
    path_b = _make_singleton(tmp_path, "b", "p2", "fix double counting bug")  # matches deterministically
    path_c = _make_singleton(tmp_path, "c", "p3", "Some other singleton")
    path_d = _make_singleton(tmp_path, "d", "p4", "Yet another singleton")

    seen_batches = []

    def fake_propose_merges(titles):
        seen_batches.append(list(titles))
        return SemanticMergeResult(groups=[])

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", fake_propose_merges)

    result = build_rollup_result([path_a, path_b, path_c, path_d])

    assert len(seen_batches) == 1
    assert "Some other singleton" in seen_batches[0]
    assert "Yet another singleton" in seen_batches[0]
    assert "Fix the double-counting bug" not in seen_batches[0]  # already a 2-session cluster
    # The deterministic pass already merged path_a/path_b into one 2-session cluster.
    multi_cluster = next(c for c in result.clusters if c.num_sessions == 2)
    assert sorted(multi_cluster.sessions) == sorted([path_a.stem, path_b.stem])


# --- issue #93: collapse_to_other / is_other_cluster / with_cumulative -----


def _cluster(title, cost, sessions=None, chapters=1, unknown=False):
    return RollupCluster(
        normalized_key=normalize_title(title),
        display_title=title,
        sessions=sessions if sessions is not None else [title.lower().replace(" ", "-")],
        num_chapters=chapters,
        cost_usd=cost,
        unknown_model_cost=unknown,
    )


def test_collapse_to_other_keeps_everything_under_threshold():
    clusters = [_cluster("A", 50.0), _cluster("B", 30.0), _cluster("C", 20.0)]
    # 50/100 = 50% < 80%, 80/100 = 80% >= 80% -> stop after B, fold C.
    collapsed = collapse_to_other(clusters, threshold=0.8)
    assert [c.display_title for c in collapsed[:2]] == ["A", "B"]
    assert len(collapsed) == 3
    assert is_other_cluster(collapsed[2])
    assert collapsed[2].cost_usd == 20.0


def test_collapse_to_other_no_collapse_when_nothing_left_over():
    clusters = [_cluster("A", 90.0), _cluster("B", 10.0)]
    collapsed = collapse_to_other(clusters, threshold=0.8)
    # Running hits 90% right at A, but there's nothing after it once B is
    # also within the kept set - wait: A alone already >= 0.8, so B is the
    # "rest" and gets folded.
    assert len(collapsed) == 2
    assert is_other_cluster(collapsed[1])


def test_collapse_to_other_never_folds_when_threshold_is_never_crossed():
    clusters = [_cluster("A", 1.0), _cluster("B", 1.0)]
    collapsed = collapse_to_other(clusters, threshold=1.5)  # unreachable fraction
    assert collapsed == clusters
    assert not any(is_other_cluster(c) for c in collapsed)


def test_collapse_to_other_empty_list_is_a_noop():
    assert collapse_to_other([], threshold=0.8) == []


def test_collapse_to_other_residual_bucket_sums_sessions_chapters_and_unknown_flag():
    clusters = [
        _cluster("A", 80.0, sessions=["s-a"]),
        _cluster("B", 10.0, sessions=["s-b"], chapters=2, unknown=True),
        _cluster("C", 10.0, sessions=["s-b", "s-c"], chapters=3),  # s-b shared with B - deduped
    ]
    collapsed = collapse_to_other(clusters, threshold=0.8)
    other = collapsed[-1]
    assert is_other_cluster(other)
    assert other.cost_usd == 20.0
    assert other.num_chapters == 5
    assert other.unknown_model_cost is True
    assert sorted(other.sessions) == ["s-b", "s-c"]  # deduped, not double-counted
    assert other.num_sessions == 2


def test_is_other_cluster_false_for_a_real_cluster():
    assert not is_other_cluster(_cluster("Real initiative", 5.0))


def test_with_cumulative_running_totals_in_order():
    clusters = [_cluster("A", 50.0), _cluster("B", 30.0), _cluster("C", 20.0)]
    paired = with_cumulative(clusters)
    assert [c.display_title for c, _cum, _pct in paired] == ["A", "B", "C"]
    assert [round(cum, 2) for _c, cum, _pct in paired] == [50.0, 80.0, 100.0]
    assert [round(pct, 1) for _c, _cum, pct in paired] == [50.0, 80.0, 100.0]


def test_with_cumulative_empty_list():
    assert with_cumulative([]) == []


def test_with_cumulative_matches_collapse_to_other_ordering():
    """The two are meant to compose - collapsing first, then computing
    cumulative over the collapsed (shorter) list, still sums to 100%."""
    clusters = [_cluster("A", 50.0), _cluster("B", 30.0), _cluster("C", 15.0), _cluster("D", 5.0)]
    collapsed = collapse_to_other(clusters, threshold=0.8)
    paired = with_cumulative(collapsed)
    assert round(paired[-1][1], 2) == 100.0
    assert round(paired[-1][2], 1) == 100.0


def test_top_n_clusters_keeps_n_costliest_and_folds_rest():
    clusters = [_cluster("A", 50.0), _cluster("B", 30.0), _cluster("C", 15.0), _cluster("D", 5.0)]
    top2 = top_n_clusters(clusters, 2)
    assert [c.display_title for c in top2[:2]] == ["A", "B"]
    assert len(top2) == 3
    assert is_other_cluster(top2[2])
    assert top2[2].cost_usd == 20.0
    assert "beyond top 2" in top2[2].display_title


def test_top_n_clusters_n_covers_everything_no_fold():
    clusters = [_cluster("A", 5.0), _cluster("B", 3.0)]
    result = top_n_clusters(clusters, 5)
    assert result == clusters
    assert not any(is_other_cluster(c) for c in result)


def test_top_n_clusters_rejects_non_positive_n():
    with pytest.raises(ValueError):
        top_n_clusters([_cluster("A", 1.0)], 0)
    with pytest.raises(ValueError):
        top_n_clusters([_cluster("A", 1.0)], -1)


def test_top_n_clusters_empty_list():
    assert top_n_clusters([], 3) == []


def test_fold_below_cost_keeps_clusters_at_or_above_floor():
    clusters = [_cluster("Big", 50.0), _cluster("Mid", 15.0), _cluster("Small", 8.0), _cluster("Tiny", 2.0)]
    result = fold_below_cost(clusters, 10.0)
    assert [c.display_title for c in result[:2]] == ["Big", "Mid"]
    assert len(result) == 3
    other = result[2]
    assert is_other_cluster(other)
    assert other.cost_usd == 10.0  # Small (8) + Tiny (2)
    assert "each under $10.00" in other.display_title


def test_fold_below_cost_nothing_below_floor_is_a_noop():
    clusters = [_cluster("A", 50.0), _cluster("B", 30.0)]
    result = fold_below_cost(clusters, 1.0)
    assert result == clusters
    assert not any(is_other_cluster(c) for c in result)


def test_fold_below_cost_everything_below_floor_folds_all():
    clusters = [_cluster("A", 5.0), _cluster("B", 3.0)]
    result = fold_below_cost(clusters, 100.0)
    assert len(result) == 1
    assert is_other_cluster(result[0])
    assert result[0].cost_usd == 8.0


def test_fold_below_cost_empty_list():
    assert fold_below_cost([], 10.0) == []


def test_fold_below_cost_residual_sums_sessions_chapters_and_unknown_flag():
    clusters = [
        _cluster("Big", 50.0, sessions=["s-a"]),
        _cluster("Small", 3.0, sessions=["s-b"], chapters=2, unknown=True),
        _cluster("Tiny", 1.0, sessions=["s-b", "s-c"], chapters=3),
    ]
    result = fold_below_cost(clusters, 10.0)
    other = result[-1]
    assert other.num_chapters == 5
    assert other.unknown_model_cost is True
    assert sorted(other.sessions) == ["s-b", "s-c"]


def test_top_n_clusters_and_fold_below_cost_compose_with_cumulative():
    clusters = [_cluster("A", 50.0), _cluster("B", 30.0), _cluster("C", 15.0), _cluster("D", 5.0)]
    for collapsed in (top_n_clusters(clusters, 2), fold_below_cost(clusters, 10.0)):
        paired = with_cumulative(collapsed)
        assert round(paired[-1][1], 2) == 100.0
        assert round(paired[-1][2], 1) == 100.0
