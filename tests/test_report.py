import sys
import types

from datetime import date

from work_ledger.activity import ActivityBucket
from work_ledger.chapters import Chapter, Section
from work_ledger.report import (
    PNG_UNAVAILABLE_MESSAGE,
    build_activity_report_html,
    build_report_html,
    build_rollup_report_html,
    build_waste_report_html,
    png_available,
)
from work_ledger.rollup import RollupCluster
from work_ledger.transcript import TranscriptTailer
from work_ledger.waste import REPEATED_READ, REPEATED_SUBAGENT, WastePattern

from .conftest import assistant_lines, user_entry, write_jsonl


def test_build_report_html_smoke(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "turn 1"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500}, [{"type": "text", "text": "x"}]),
    ]
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()

    chapters = [Chapter(title="Build the thing", category="feature-build", sections=[Section(title="step", prompt_ids=["p1"])])]
    html = build_report_html("s.jsonl", tailer, chapters, pass_cost_usd=0.002)

    assert html.startswith("<!doctype html>")
    assert "Build the thing" in html
    assert "s.jsonl" in html
    assert "</html>" in html


def test_build_report_html_zero_chapters_does_not_crash(tmp_path):
    path = tmp_path / "s.jsonl"
    write_jsonl(path, [])
    tailer = TranscriptTailer(path)
    tailer.poll()

    html = build_report_html("empty.jsonl", tailer, [], pass_cost_usd=0.0)
    assert "<!doctype html>" in html


def _cluster(title, sessions, num_chapters=1, cost=1.0):
    c = RollupCluster(normalized_key=title.lower(), display_title=title, num_chapters=num_chapters, cost_usd=cost)
    c.sessions.extend(sessions)
    return c


def test_build_rollup_report_html_smoke():
    clusters = [
        _cluster("Fix the double-counting bug", ["s1", "s2"], num_chapters=2, cost=12.5),
        _cluster("Write onboarding docs", ["s3"], num_chapters=1, cost=3.0),
    ]
    html = build_rollup_report_html(clusters, n_sessions_included=3, n_sessions_total=3)

    assert html.startswith("<!doctype html>")
    assert "work-ledger rollup" in html
    assert "Fix the double-counting bug" in html
    assert "Write onboarding docs" in html
    assert "$15.50" in html  # grand total stat tile
    assert "</html>" in html


def test_build_rollup_report_html_recurring_count_only_counts_multi_session_clusters():
    clusters = [
        _cluster("Recurring thing", ["s1", "s2"], cost=5.0),
        _cluster("One-off thing", ["s3"], cost=1.0),
    ]
    html = build_rollup_report_html(clusters, n_sessions_included=3, n_sessions_total=3)
    assert ">1<" in html  # exactly one cluster touched more than one session


def test_build_rollup_report_html_top_scope_note_shows_included_vs_total():
    clusters = [_cluster("X", ["s1"], cost=1.0)]
    html = build_rollup_report_html(clusters, n_sessions_included=2, n_sessions_total=10, top=2)
    assert "top 2 sessions by cost" in html
    assert "of 10 found in range" in html


def test_build_rollup_report_html_date_range_scope_note():
    clusters = [_cluster("X", ["s1"], cost=1.0)]
    html = build_rollup_report_html(
        clusters, n_sessions_included=1, n_sessions_total=1, since=date(2026, 8, 1), until=date(2026, 8, 12)
    )
    assert "2026-08-01 to 2026-08-12" in html


def test_build_rollup_report_html_zero_clusters_does_not_crash():
    html = build_rollup_report_html([], n_sessions_included=0, n_sessions_total=0)
    assert "<!doctype html>" in html


def test_build_activity_report_html_smoke():
    buckets = [
        ActivityBucket("Tool: Bash", 50.0),
        ActivityBucket("Direct response (no tool call)", 30.0),
        ActivityBucket("Other/final 20% (3 categories)", 20.0),
    ]
    html = build_activity_report_html("s.jsonl", buckets, total_n_buckets=5)

    assert html.startswith("<!doctype html>")
    assert "Tool: Bash" in html
    assert "Other/final 20% (3 categories)" in html
    assert "s.jsonl" in html
    assert "</html>" in html
    # The residual bucket must render in the neutral overflow color, not
    # a categorical slot - it's a sum of unrelated activity types.
    assert "var(--overflow)" in html


def test_build_activity_report_html_recognizes_top_n_residual_label():
    """top_n() (a hard count cutoff) labels its residual bucket
    "Other/rest (...)" rather than collapse_to_other's "Other/final N%" -
    both must be detected as the residual bucket and get the neutral
    overflow color, not a categorical slot."""
    buckets = [ActivityBucket("Tool: Bash", 50.0), ActivityBucket("Other/rest (3 categories)", 20.0)]
    html = build_activity_report_html("s.jsonl", buckets, total_n_buckets=4)
    assert "var(--overflow)" in html


def test_build_activity_report_html_no_residual_bucket():
    """Not every call has a residual bucket (e.g. threshold=1.0, or fewer
    buckets than needed to cross the threshold) - must not crash looking
    for one that isn't there."""
    buckets = [ActivityBucket("Tool: Bash", 50.0), ActivityBucket("Tool: Edit", 50.0)]
    html = build_activity_report_html("s.jsonl", buckets, total_n_buckets=2)
    assert "<!doctype html>" in html
    assert "var(--overflow)" not in html


def test_build_activity_report_html_zero_buckets_does_not_crash():
    html = build_activity_report_html("empty.jsonl", [], total_n_buckets=0)
    assert "<!doctype html>" in html


def test_build_activity_report_html_zero_cost_with_residual_bucket_does_not_crash():
    """Regression test: a zero-cost transcript (e.g. all turns hit unknown/
    unpriced models) with an "Other/final" bucket present used to raise
    ZeroDivisionError computing other_pct - must degrade to 0%, not crash."""
    buckets = [ActivityBucket("Tool: Bash", 0.0), ActivityBucket("Other/final 20% (2 categories)", 0.0)]
    html = build_activity_report_html("s.jsonl", buckets, total_n_buckets=3)
    assert "<!doctype html>" in html


def test_build_timeline_report_html_smoke():
    from work_ledger.timeline import DayBucket

    days = [
        DayBucket(day="2026-07-01", activity_counts={"Tool: Bash": 2}, category_counts={"bug-fix": 1}),
        DayBucket(day="2026-07-02", activity_counts={"Tool: Bash": 1, "Skill: dataviz": 1}, category_counts={}),
    ]
    from work_ledger.report import build_timeline_report_html

    html = build_timeline_report_html(
        "2026-07-01 to 2026-07-02",
        days,
        top_activity=["Tool: Bash", "Skill: dataviz"],
        top_categories=["bug-fix"],
        total_sessions=2,
        uncached_sessions=1,
    )
    assert html.startswith("<!doctype html>")
    assert "2026-07-01" in html
    assert "Tool: Bash" in html
    assert "timeline backfill" in html
    assert "</html>" in html


def test_build_timeline_report_html_zero_days_does_not_crash():
    from work_ledger.report import build_timeline_report_html

    html = build_timeline_report_html(
        "empty range", [], top_activity=[], top_categories=[], total_sessions=0, uncached_sessions=0
    )
    assert "<!doctype html>" in html


def test_build_timeline_report_html_includes_narrative_when_enough_data():
    """summarize_timeline() is called unconditionally by the report builder
    (not behind a flag) - given enough data it should land in the HTML."""
    from work_ledger.report import build_timeline_report_html
    from work_ledger.timeline import DayBucket

    days = [
        DayBucket(day="2026-07-01", category_counts={"debugging": 3}),
        DayBucket(day="2026-07-02", category_counts={"debugging": 2, "design-planning": 1}),
        DayBucket(day="2026-07-03", category_counts={"refactor": 3}),
        DayBucket(day="2026-07-04", category_counts={"refactor": 2, "docs": 1}),
    ]
    html = build_timeline_report_html(
        "2026-07-01 to 2026-07-04",
        days,
        top_activity=[],
        top_categories=["debugging", "refactor", "design-planning", "docs"],
        total_sessions=4,
        uncached_sessions=0,
    )
    assert 'class="narrative"' in html
    assert "Early in this range" in html
    assert "debugging" in html
    assert "More recently" in html
    assert "refactor" in html


def test_build_timeline_report_html_omits_narrative_when_not_enough_data():
    from work_ledger.report import build_timeline_report_html
    from work_ledger.timeline import DayBucket

    days = [
        DayBucket(day="2026-07-01", activity_counts={"Tool: Bash": 2}, category_counts={"bug-fix": 1}),
        DayBucket(day="2026-07-02", activity_counts={"Tool: Bash": 1}, category_counts={}),
    ]
    html = build_timeline_report_html(
        "2026-07-01 to 2026-07-02",
        days,
        top_activity=["Tool: Bash"],
        top_categories=["bug-fix"],
        total_sessions=2,
        uncached_sessions=0,
    )
    assert 'class="narrative"' not in html


# --- png_available (used by `miso --check-status`) -------------------------
#
# Mocks sys.modules directly rather than depending on whether Playwright is
# actually installed on whatever machine runs this suite - CI deliberately
# doesn't install the `report` extra (see .github/workflows/ci.yml), so a
# test asserting the "available" branch must not depend on a real import
# succeeding, and one asserting "unavailable" must not depend on it failing.


def test_png_available_true_when_importable(monkeypatch):
    fake_playwright = types.ModuleType("playwright")
    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    ok, msg = png_available()
    assert ok is True
    assert "installed" in msg.lower()


def test_png_available_false_when_not_importable(monkeypatch):
    # A None entry in sys.modules blocks that name from importing at all -
    # this is true regardless of whether "playwright.sync_api" itself is
    # already cached (real or fake) from an earlier import in this process,
    # since the parent package import is what's blocked.
    monkeypatch.setitem(sys.modules, "playwright", None)

    ok, msg = png_available()
    assert ok is False
    assert msg == PNG_UNAVAILABLE_MESSAGE


def test_build_trend_report_html_smoke():
    from work_ledger.report import build_trend_report_html
    from work_ledger.trend import CostBucket

    buckets = [
        CostBucket(period="2026-07-01", cost_usd=1.5, num_turns=3),
        CostBucket(period="2026-07-02", cost_usd=3.25, num_turns=5),
    ]
    html = build_trend_report_html("2026-07-01 to 2026-07-02", buckets, bucket_size="day", total_sessions=2)

    assert html.startswith("<!doctype html>")
    assert "work-ledger trend" in html
    assert "2026-07-01" in html
    assert "$4.75" in html  # total cost stat tile (1.5 + 3.25)
    assert "</html>" in html


def test_build_trend_report_html_week_bucket_label():
    from work_ledger.report import build_trend_report_html
    from work_ledger.trend import CostBucket

    buckets = [CostBucket(period="2026-06-29", cost_usd=10.0, num_turns=4)]
    html = build_trend_report_html("2026-06-29 to 2026-07-05", buckets, bucket_size="week", total_sessions=1)
    assert "cost by week" in html
    assert "Average per week" in html


def test_build_trend_report_html_flags_unknown_model_cost():
    from work_ledger.report import build_trend_report_html
    from work_ledger.trend import CostBucket

    buckets = [
        CostBucket(period="2026-07-01", cost_usd=1.0, num_turns=1),
        CostBucket(period="2026-07-02", cost_usd=0.0, num_turns=1, unknown_model_cost=True),
    ]
    html = build_trend_report_html("2026-07-01 to 2026-07-02", buckets, bucket_size="day", total_sessions=1)
    assert "floor, not exact" in html
    assert "1 of 2" in html  # pricing coverage stat tile


def test_build_trend_report_html_zero_buckets_does_not_crash():
    from work_ledger.report import build_trend_report_html

    html = build_trend_report_html("empty range", [], bucket_size="day", total_sessions=0)
    assert "<!doctype html>" in html
    assert "</html>" in html


def test_build_waste_report_html_smoke():
    patterns = [
        WastePattern(kind=REPEATED_SUBAGENT, scope="Research", label="Explore: research the API", occurrences=3, cost_usd=1.5),
        WastePattern(kind=REPEATED_READ, scope="Research", label="/repo/foo.py", occurrences=2, cost_usd=0.002),
    ]
    html = build_waste_report_html("s.jsonl", patterns)
    assert html.startswith("<!doctype html>")
    assert "s.jsonl" in html
    assert "/repo/foo.py" in html
    assert "research the API" in html
    assert "Repeated file read" in html
    assert "Repeated subagent dispatch" in html
    assert "</html>" in html


def test_build_waste_report_html_zero_patterns_does_not_crash():
    html = build_waste_report_html("empty.jsonl", [])
    assert "<!doctype html>" in html
    assert "</html>" in html


# --- footer (issue #75's "About" block) -----------------------------------


def _fake_about_info(**overrides):
    from work_ledger.about import AboutInfo

    defaults = dict(
        description="Lightweight, near-real-time Claude Code usage/cost tracker for individuals",
        version="9.9.9",
        last_updated="2026-07-20T10:00:00+00:00",
        commit="deadbee",
        author_email="davehk@gmail.com",
        author_url="www.dhk.io",
        repo_url="https://github.com/dhk/work-ledger",
    )
    defaults.update(overrides)
    return AboutInfo(**defaults)


def test_build_report_html_includes_footer(monkeypatch, tmp_path):
    import work_ledger.report as report_mod

    monkeypatch.setattr(report_mod, "get_about_info", lambda: _fake_about_info())

    path = tmp_path / "s.jsonl"
    write_jsonl(path, [])
    tailer = TranscriptTailer(path)
    tailer.poll()

    html = build_report_html("s.jsonl", tailer, [], pass_cost_usd=0.0)
    assert "work-ledger v9.9.9" in html
    assert "deadbee" in html
    assert "github.com/dhk/work-ledger" in html


def test_build_activity_report_html_includes_footer(monkeypatch):
    import work_ledger.report as report_mod

    monkeypatch.setattr(report_mod, "get_about_info", lambda: _fake_about_info())

    buckets = [ActivityBucket("Tool: Bash", 5.0)]
    html = build_activity_report_html("s.jsonl", buckets, total_n_buckets=1)
    assert "work-ledger v9.9.9" in html
    assert "deadbee" in html


def test_footer_falls_back_to_last_updated_date_when_no_commit(monkeypatch):
    import work_ledger.report as report_mod

    monkeypatch.setattr(report_mod, "get_about_info", lambda: _fake_about_info(commit=None))

    buckets = [ActivityBucket("Tool: Bash", 5.0)]
    html = build_activity_report_html("s.jsonl", buckets, total_n_buckets=1)
    assert "2026-07-20" in html
