from work_ledger.activity import ActivityBucket
from work_ledger.chapters import Chapter, Section
from work_ledger.report import build_activity_report_html, build_report_html
from work_ledger.transcript import TranscriptTailer

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
