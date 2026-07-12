"""Load entries from the shared pattern library (see
docs/pattern-library-design.md) - known mistakes/patterns/fixes that
`recommend` can surface alongside its own local rules.

v1 matching mechanism (an implementation decision the design doc left
open - see its "not a generic DSL" non-goal): each entry optionally
declares `maps_to`, the `rule_id` of an existing `recommend.py` rule it
enriches. `recommend` only ever surfaces a library entry alongside a
local rule that actually fired with a matching `rule_id` - there is no
independent pattern-matching against arbitrary transcript features.

Content lives as plain files (one per entry) rather than a database -
readable, diffable, PR-reviewed, same trust model as the rest of this
project. This module only reads that content; it never writes it (see
pattern_client.py for the separate, network-touching report_recommended/
report_used counters).
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Content lives at the repo root, a sibling of the work_ledger/ package -
# works today for anyone running from a checkout (how this project is
# developed and tested throughout). Shipping this content inside a
# PyPI-distributed wheel as proper package data is a packaging follow-up,
# not solved here - see docs/pattern-library-design.md.
DEFAULT_PATTERNS_DIR = Path(__file__).resolve().parent.parent / "patterns"

# Also used by pattern_client.py to validate a pattern id before building
# a report URL - imported from here rather than duplicated, so the two
# checks can't silently drift apart.
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

CATEGORIES: tuple[str, ...] = (
    "cost",
    "user-actions",
    "configuration",
    "new-skill",
    "new-tool",
)

_SECTION_NAMES = ("Pattern", "Use Case", "Diagnosis", "Fix")


@dataclass
class PatternEntry:
    id: str
    title: str
    category: str
    maps_to_rule_id: str | None
    pattern: str
    use_case: str
    diagnosis: str
    fix: str
    recommended_count: int = 0
    used_count: int = 0


class PatternFileError(ValueError):
    """A pattern file didn't match the required shape - see
    CONTRIBUTING-patterns.md and patterns/TEMPLATE.md."""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise PatternFileError("missing frontmatter (must start with '---')")
    end = text.find("\n---", 3)
    if end == -1:
        raise PatternFileError("unterminated frontmatter block")
    fm_block = text[3:end].strip()
    body = text[end + 4 :]
    data = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        data[key.strip()] = value.strip()
    return data, body


def _extract_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(body)
    if not m:
        raise PatternFileError(f"missing required section: '## {heading}'")
    return m.group(1).strip()


def parse_pattern_file(path: Path) -> PatternEntry:
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)

    missing = [k for k in ("id", "title", "category") if not fm.get(k)]
    if missing:
        raise PatternFileError(f"missing required frontmatter field(s): {', '.join(missing)}")

    entry_id = fm["id"]
    if not ID_PATTERN.match(entry_id):
        raise PatternFileError(f"id {entry_id!r} must be a kebab-case slug (lowercase letters/digits/hyphens)")
    if entry_id != path.stem:
        raise PatternFileError(
            f"id {entry_id!r} must match the filename exactly (expected {path.stem!r} for {path.name}) - "
            "see CONTRIBUTING-patterns.md"
        )

    category = fm["category"]
    if category not in CATEGORIES:
        raise PatternFileError(f"unknown category {category!r}, expected one of {CATEGORIES}")

    sections = {name: _extract_section(body, name) for name in _SECTION_NAMES}

    try:
        recommended_count = int(fm.get("recommended_count", 0) or 0)
        used_count = int(fm.get("used_count", 0) or 0)
    except ValueError as e:
        raise PatternFileError(f"recommended_count/used_count must be integers: {e}") from e

    return PatternEntry(
        id=fm["id"],
        title=fm["title"],
        category=category,
        maps_to_rule_id=fm.get("maps_to") or None,
        pattern=sections["Pattern"],
        use_case=sections["Use Case"],
        diagnosis=sections["Diagnosis"],
        fix=sections["Fix"],
        recommended_count=recommended_count,
        used_count=used_count,
    )


def load_patterns(patterns_dir: Path) -> list[PatternEntry]:
    """Load every entry in `patterns_dir`, skipping TEMPLATE.md. A single
    malformed entry is skipped rather than crashing the whole load - same
    graceful-degradation philosophy as the rest of this tool (a bad cache
    entry or unreadable subagent transcript doesn't take down the CLI)."""
    if not patterns_dir.is_dir():
        return []
    entries = []
    for path in sorted(patterns_dir.glob("*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            entries.append(parse_pattern_file(path))
        except (OSError, PatternFileError):
            continue
    return entries


def patterns_for_rule(entries: list[PatternEntry], rule_id: str) -> list[PatternEntry]:
    return [e for e in entries if e.maps_to_rule_id == rule_id]
