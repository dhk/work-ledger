"""Lightweight, narrowly-scoped extraction of ticket IDs and PR/issue
references from user-authored prompt text - so a turn (especially one
that lands in chapters.py's "Unsorted" bucket, where a raw 60-char
prompt snippet is often the only identifying text available) can show
something more useful than that snippet alone.

Same "short token only, never a full-text capture" scoping precedent
transcript.py's tool_call_signature (first 3 words of a Bash command) and
read_paths (Read tool targets) already establish - this extracts short
alphanumeric tokens, not prompt content wholesale.

Ticket-ID detection is inherently fuzzy without knowing an org's actual
prefix convention - a JIRA-style ID ("SLA-42") is syntactically identical
to a version/standard/model name ("ISO-8601", "GPT-4", "UTF-8").
WORK_LEDGER_TICKET_PREFIX lets you name your real prefixes for exact
matching (no false positives); unset, a generic pattern plus a small
stoplist of common non-ticket prefixes is used instead, best-effort only
- never presented as authoritative.
"""

import os
import re

# JIRA-style: 2-10 uppercase-alnum chars, a dash, 1-6 digits. Deliberately
# requires a leading letter (excludes bare numeric ranges like "2026-08").
_GENERIC_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")

# "#123" - a leading word-char, slash, or another # immediately before
# excludes things like "issue123#" fragments or a second # in "a#b#123"
# from matching as a fresh reference at the wrong boundary.
_PR_RE = re.compile(r"(?<![\w/#])#(\d{1,6})\b")

# Common false-positive prefixes the generic ticket pattern would
# otherwise match - encoding/standard/model names people type constantly,
# never real ticket prefixes in practice. Not exhaustive - best-effort
# only, exactly why WORK_LEDGER_TICKET_PREFIX exists for anyone who wants
# precision instead.
_STOPLIST_PREFIXES = frozenset(
    {
        "UTF", "ISO", "GPT", "HTTP", "HTTPS", "SHA", "OAUTH", "JSON", "HTML",
        "CSS", "SQL", "URL", "URI", "API", "CLI", "PDF", "PNG", "JPG", "CSV",
        "XML", "YAML", "TOML", "IPV", "TCP", "UDP", "SSH", "TLS", "SSL", "IDE",
    }
)


def _configured_ticket_prefixes() -> list[str] | None:
    raw = os.environ.get("WORK_LEDGER_TICKET_PREFIX", "").strip()
    if not raw:
        return None
    return [p.strip().upper() for p in raw.split(",") if p.strip()]


def extract_ticket_refs(text: str) -> list[str]:
    """Ticket-ID-like tokens (e.g. "SLA-42"), first-seen order, deduped.
    Uses WORK_LEDGER_TICKET_PREFIX for exact matching when set (your real
    prefixes only, no false positives); falls back to the generic pattern
    plus the stoplist above when unset - best-effort only."""
    if not text:
        return []
    prefixes = _configured_ticket_prefixes()
    seen: list[str] = []
    for m in _GENERIC_TICKET_RE.finditer(text):
        ref = m.group(1)
        prefix = ref.split("-")[0]
        if prefixes is not None:
            if prefix not in prefixes:
                continue
        elif prefix in _STOPLIST_PREFIXES:
            continue
        if ref not in seen:
            seen.append(ref)
    return seen


def extract_pr_refs(text: str) -> list[str]:
    """"#123"-style references, first-seen order, deduped. Doesn't (can't)
    distinguish issue vs PR from text alone - pr_url() below deliberately
    uses a GitHub URL shape that resolves correctly either way."""
    if not text:
        return []
    seen: list[str] = []
    for m in _PR_RE.finditer(text):
        ref = m.group(1)
        if ref not in seen:
            seen.append(ref)
    return seen


def ticket_url(ref: str) -> str | None:
    """A clickable URL for `ref`, built from WORK_LEDGER_TICKET_URL_TEMPLATE
    (e.g. "https://yourorg.atlassian.net/browse/{id}"). None - never a
    guessed URL - if unset."""
    template = os.environ.get("WORK_LEDGER_TICKET_URL_TEMPLATE", "").strip()
    if not template:
        return None
    return template.replace("{id}", ref)


def pr_url(ref: str) -> str | None:
    """A clickable URL for PR/issue `ref`, built from
    WORK_LEDGER_GITHUB_REPO (e.g. "dhk/work-ledger"). None if unset.
    Uses /issues/<n> rather than /pull/<n> - GitHub resolves that
    correctly whether <n> is actually an issue or a PR, which /pull/<n>
    alone would not for an issue."""
    repo = os.environ.get("WORK_LEDGER_GITHUB_REPO", "").strip()
    if not repo:
        return None
    return f"https://github.com/{repo}/issues/{ref}"


_FILLER_PREFIX_RE = re.compile(
    r"^(ok|okay|so|well|alright|hey|now|great|cool|right)[,.\s]+", re.IGNORECASE
)


def clean_synopsis(text: str, max_len: int = 80) -> str:
    """A slightly more readable one-liner than a raw prompt snippet -
    strips a leading filler word ("ok, ", "so, ", "let's " has no fixed
    stoplist entry since "let's" is often load-bearing, e.g. "let's not"),
    collapses whitespace, and truncates at a word boundary rather than
    mid-word. Purely cosmetic - never changes meaning, never invents
    content. Falls back to the input unchanged if stripping the filler
    prefix would leave nothing."""
    if not text:
        return text
    cleaned = " ".join(text.split())
    stripped = _FILLER_PREFIX_RE.sub("", cleaned, count=1)
    if stripped != cleaned and stripped:
        # A filler prefix was actually removed - re-capitalize the new
        # leading word so the result still reads as a sentence start.
        # Text with no filler prefix is left exactly as typed, case
        # included - not this function's place to relabel real content.
        cleaned = stripped[0].upper() + stripped[1:]
    if len(cleaned) <= max_len:
        return cleaned
    truncated = cleaned[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len * 0.6:  # don't chop a short word down to nothing
        truncated = truncated[:last_space]
    return truncated + "…"
