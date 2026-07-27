"""The "About" block `CLAUDE.md`'s "CLI/MCP command conventions" section
requires (issue #75, see docs/about-block-design.md) - one shared
computation, reused by every user-facing surface (`work-ledger about`,
`work-ledger-mcp`'s `about` tool, `serve`'s footer, every generated
report's footer) rather than four separate implementations that could
drift.

Static metadata about the running code only - what version/commit is
this, who wrote it, where does it live - never a network call, never
usage data (unrelated to pattern_client.py's opt-in counters), and never
worth crashing a command over: get_about_info() degrades instead of
raising for any reason.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from work_ledger import cycle

DESCRIPTION = "Lightweight, near-real-time Claude Code usage/cost tracker for individuals"
AUTHOR_EMAIL = "davehk@gmail.com"
AUTHOR_URL = "www.dhk.io"
REPO_URL = "https://github.com/dhk/work-ledger"


@dataclass
class AboutInfo:
    description: str
    version: str
    last_updated: str  # ISO date/time, best available source
    commit: str | None  # short SHA, only when resolvable - never guessed
    author_email: str
    author_url: str
    repo_url: str


def _git(*args: str, cwd: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=5
    )
    return result.stdout.strip()


def _editable_git_info(repo_root: Path) -> tuple[str, str] | None:
    """(commit, last_updated) from the repo at `repo_root`'s own git log,
    or None if any git call fails for any reason at all (git not
    installed, `repo_root` not actually a repo despite the install-mode
    heuristic saying so, a shallow clone with no log, whatever) - the
    caller degrades to the file-mtime fallback rather than propagating."""
    try:
        commit = _git("rev-parse", "--short", "HEAD", cwd=repo_root)
        last_updated = _git("log", "-1", "--format=%cI", cwd=repo_root)
    except Exception:
        return None
    if not commit or not last_updated:
        return None
    return commit, last_updated


def _file_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def get_about_info() -> AboutInfo:
    """Never raises - worst case, returns an AboutInfo with commit=None and
    a best-effort last_updated (this module's own file mtime, or - if even
    that stat() fails - the current time)."""
    try:
        version = metadata.version(cycle.PACKAGE_NAME)
    except Exception:
        version = "unknown"

    commit: str | None = None
    last_updated: str | None = None

    try:
        install = cycle.detect_install_mode()
    except Exception:
        install = None

    if install is not None and install.mode == cycle.EDITABLE and install.repo_root is not None:
        resolved = _editable_git_info(install.repo_root)
        if resolved is not None:
            commit, last_updated = resolved

    if last_updated is None:
        try:
            last_updated = _file_mtime_iso(Path(__file__))
        except Exception:
            last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return AboutInfo(
        description=DESCRIPTION,
        version=version,
        last_updated=last_updated,
        commit=commit,
        author_email=AUTHOR_EMAIL,
        author_url=AUTHOR_URL,
        repo_url=REPO_URL,
    )
