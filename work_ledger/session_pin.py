"""Pin a specific session so every command defaults to it instead of "most
recently active," until explicitly cleared - see `work-ledger session`.

Stores the resolved transcript's absolute path, not the raw --session
prefix the user typed when pinning: re-resolving a prefix against
~/.claude/projects/ on every single command invocation would be wasteful,
and a prefix that was unambiguous at pin time could later collide with a
new session using the same prefix. Pinning up front, once, avoids both.
"""

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "work-ledger"
PINNED_SESSION_PATH = CONFIG_DIR / "pinned_session"


def get_pinned_session() -> Path | None:
    """The currently pinned transcript path, or None if nothing's pinned -
    including if the pinned file no longer exists on disk. A stale pin
    (the session was deleted/moved since) degrades to "nothing pinned"
    rather than a hard error on every subsequent command."""
    if not PINNED_SESSION_PATH.exists():
        return None
    try:
        raw = PINNED_SESSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def set_pinned_session(path: Path) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PINNED_SESSION_PATH.write_text(str(path.resolve()), encoding="utf-8")


def clear_pinned_session() -> None:
    try:
        PINNED_SESSION_PATH.unlink()
    except FileNotFoundError:
        pass
