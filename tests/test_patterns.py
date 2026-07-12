from work_ledger.patterns import (
    DEFAULT_PATTERNS_DIR,
    PatternFileError,
    load_patterns,
    parse_pattern_file,
    patterns_for_rule,
)

VALID_ENTRY = """---
id: repeated-thing
title: Repeated thing happens
category: cost
maps_to: outlier-chapter-cost
recommended_count: 3
used_count: 1
---

## Pattern

Something recurs.

## Use Case

It showed up in session X.

## Diagnosis

Because of Y.

## Fix

Do Z.
"""


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_valid_entry(tmp_path):
    path = _write(tmp_path, "repeated-thing.md", VALID_ENTRY)
    entry = parse_pattern_file(path)
    assert entry.id == "repeated-thing"
    assert entry.title == "Repeated thing happens"
    assert entry.category == "cost"
    assert entry.maps_to_rule_id == "outlier-chapter-cost"
    assert entry.pattern == "Something recurs."
    assert entry.use_case == "It showed up in session X."
    assert entry.diagnosis == "Because of Y."
    assert entry.fix == "Do Z."
    assert entry.recommended_count == 3
    assert entry.used_count == 1


def test_parse_missing_frontmatter_raises(tmp_path):
    path = _write(tmp_path, "bad.md", "## Pattern\nfoo\n")
    try:
        parse_pattern_file(path)
        assert False, "should have raised"
    except PatternFileError:
        pass


def test_parse_missing_required_field_raises(tmp_path):
    text = VALID_ENTRY.replace("title: Repeated thing happens\n", "")
    path = _write(tmp_path, "bad.md", text)
    try:
        parse_pattern_file(path)
        assert False, "should have raised"
    except PatternFileError as e:
        assert "title" in str(e)


def test_parse_unknown_category_raises(tmp_path):
    text = VALID_ENTRY.replace("category: cost", "category: not-a-real-category")
    path = _write(tmp_path, "bad.md", text)
    try:
        parse_pattern_file(path)
        assert False, "should have raised"
    except PatternFileError as e:
        assert "category" in str(e)


def test_parse_missing_section_raises(tmp_path):
    text = VALID_ENTRY.replace("## Fix\n\nDo Z.\n", "")
    path = _write(tmp_path, "bad.md", text)
    try:
        parse_pattern_file(path)
        assert False, "should have raised"
    except PatternFileError as e:
        assert "Fix" in str(e)


def test_maps_to_optional(tmp_path):
    text = VALID_ENTRY.replace("maps_to: outlier-chapter-cost\n", "")
    path = _write(tmp_path, "no-map.md", text)
    entry = parse_pattern_file(path)
    assert entry.maps_to_rule_id is None


def test_load_patterns_skips_template_and_malformed(tmp_path):
    _write(tmp_path, "TEMPLATE.md", "not a real entry, just a template")
    _write(tmp_path, "good.md", VALID_ENTRY)
    _write(tmp_path, "malformed.md", "not frontmatter at all")

    entries = load_patterns(tmp_path)
    assert len(entries) == 1
    assert entries[0].id == "repeated-thing"


def test_load_patterns_missing_dir_returns_empty(tmp_path):
    assert load_patterns(tmp_path / "does-not-exist") == []


def test_patterns_for_rule_filters_correctly(tmp_path):
    other = VALID_ENTRY.replace("id: repeated-thing", "id: other-thing").replace(
        "maps_to: outlier-chapter-cost", "maps_to: subagent-heavy-chapter"
    )
    _write(tmp_path, "a.md", VALID_ENTRY)
    _write(tmp_path, "b.md", other)

    entries = load_patterns(tmp_path)
    matches = patterns_for_rule(entries, "outlier-chapter-cost")
    assert [e.id for e in matches] == ["repeated-thing"]


def test_real_seeded_entry_parses(tmp_path):
    """The one real, checked-in entry (patterns/outlier-chapter-cost-review.md)
    must parse cleanly - a regression test against the actual shipped content,
    not just synthetic fixtures."""
    entries = load_patterns(DEFAULT_PATTERNS_DIR)
    ids = [e.id for e in entries]
    assert "outlier-chapter-cost-review" in ids
    entry = next(e for e in entries if e.id == "outlier-chapter-cost-review")
    assert entry.maps_to_rule_id == "outlier-chapter-cost"
    assert entry.category == "cost"
