"""Correlate a session to its own git repo's commit history during the
session's time window - "what was actually done," not just what the
prompts said. Tier 1 of the design conversation in
docs/mcp-session-tools-design.md's neighborhood (see issue #87 for Tier
2, real PR titles/descriptions/review state via the GitHub API -
deliberately not built here).

Entirely local: reads the session's own `cwd` (TranscriptTailer.cwd,
captured from the transcript's own `cwd` field - see transcript.py) and
runs `git log`/`git remote` in that directory, the same local-subprocess
precedent about.py already uses for its own commit/version detection.
No GitHub API call, no token, no new network path - commit/PR links are
built from `git remote get-url origin` plus a SHA or a "#NNN" already
present in a commit's own subject line (GitHub's merge/squash commits
say "Merge pull request #85" or end "(#85)" - the exact `#\\d+` pattern
references.py's extract_pr_refs already looks for, just pointed at git
log output instead of prompt text).

Correlation is a time-window heuristic, not proof: a commit landing in
[session's first turn, session's last turn] in the session's own `cwd`
isn't provably *from* that session - a teammate, or a second terminal,
could commit to the same repo in that window too. Always presented as
"commits during this session," never "commits from this session." Also
degrades to unavailable, for any reason at all (no cwd recorded, the
directory no longer exists, it's not a git repo, git isn't installed, a
git call times out) - a session's repo very often won't still be present
on whatever machine is running `work-ledger serve` (a different machine,
a deleted checkout, an ephemeral environment), and that's routine, not
an error.
"""

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from work_ledger.references import extract_pr_refs

_GIT_TIMEOUT_S = 5
_LOG_SEP = "\x1f"  # unit separator - won't appear in a real commit subject
# Commits right at a session's exact start/end boundary shouldn't be
# missed over an off-by-a-few-seconds timestamp mismatch between the
# transcript's own clock and git's - small, fixed padding either side.
_BOUNDARY_PADDING = timedelta(minutes=2)


@dataclass
class Commit:
    sha: str
    short_sha: str
    subject: str
    author_date: str  # ISO 8601, as `git log --pretty=%cI` prints it
    pr_refs: list[str] = field(default_factory=list)


@dataclass
class GitActivity:
    repo_available: bool
    commits: list[Commit] = field(default_factory=list)
    # "owner/repo", parsed from `origin`'s URL, only when it's a github.com
    # remote - None for anything else (no remote, a non-GitHub host,
    # self-hosted GitHub Enterprise not currently handled).
    remote_owner_repo: str | None = None


def _run_git(args: list[str], cwd: Path) -> str | None:
    """None for any failure at all (git missing, not a repo, timeout,
    non-zero exit) - every caller here treats that as "can't answer,"
    never as an error worth surfacing."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_GIT_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


_GITHUB_SSH_RE = re.compile(r"^git@github\.com:([^/]+)/(.+?)(\.git)?$")
_GITHUB_HTTPS_RE = re.compile(r"^https://github\.com/([^/]+)/(.+?)(\.git)?/?$")


def _parse_github_owner_repo(remote_url: str) -> str | None:
    """"git@github.com:owner/repo.git" or "https://github.com/owner/repo"
    (.git suffix optional either way) -> "owner/repo". None for any other
    host (self-hosted, GitLab, Bitbucket, ...) - never guessed."""
    remote_url = remote_url.strip()
    m = _GITHUB_SSH_RE.match(remote_url) or _GITHUB_HTTPS_RE.match(remote_url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def find_git_activity(cwd: str | None, since_ts: str, until_ts: str) -> GitActivity:
    """`since_ts`/`until_ts` are the session's first/last turn timestamps
    (ISO 8601, e.g. Turn.timestamp) - padded by _BOUNDARY_PADDING before
    being handed to `git log --since/--until`, which parses ISO 8601
    directly. repo_available=False (never an exception) when `cwd` is
    unset, doesn't exist, or isn't a git repo - the routine case for an
    older or moved session, not a failure to report loudly."""
    if not cwd:
        return GitActivity(repo_available=False)
    path = Path(cwd)
    if not path.is_dir():
        return GitActivity(repo_available=False)

    is_repo = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    if is_repo is None or is_repo.strip() != "true":
        return GitActivity(repo_available=False)

    since_dt = _parse_iso(since_ts)
    until_dt = _parse_iso(until_ts)
    since_arg = (since_dt - _BOUNDARY_PADDING).isoformat() if since_dt else since_ts
    until_arg = (until_dt + _BOUNDARY_PADDING).isoformat() if until_dt else until_ts

    log_out = _run_git(
        ["log", f"--since={since_arg}", f"--until={until_arg}", f"--pretty=format:%H{_LOG_SEP}%s{_LOG_SEP}%cI"],
        cwd=path,
    )
    commits = []
    for line in (log_out or "").splitlines():
        parts = line.split(_LOG_SEP)
        if len(parts) != 3:
            continue
        sha, subject, author_date = parts
        commits.append(Commit(sha=sha, short_sha=sha[:8], subject=subject, author_date=author_date, pr_refs=extract_pr_refs(subject)))

    remote_url = _run_git(["remote", "get-url", "origin"], cwd=path)
    owner_repo = _parse_github_owner_repo(remote_url) if remote_url else None

    return GitActivity(repo_available=True, commits=commits, remote_owner_repo=owner_repo)


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def commit_url(owner_repo: str | None, sha: str) -> str | None:
    """None - never a guessed URL - when the remote isn't a recognized
    GitHub URL (or there's no remote at all)."""
    return f"https://github.com/{owner_repo}/commit/{sha}" if owner_repo else None


def pr_url_from_commit(owner_repo: str | None, pr_ref: str) -> str | None:
    """Same /issues/<n> shape as references.py's pr_url - GitHub resolves
    that correctly whether <n> is actually an issue or a PR."""
    return f"https://github.com/{owner_repo}/issues/{pr_ref}" if owner_repo else None
