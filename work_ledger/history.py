"""Local sqlite-backed session history store (issue #42) - one row per
session transcript, kept incrementally in sync so cross-session features
(#3's rollup, #4's trend, #5's cross-session waste half) have a persisted
place to build on instead of each re-deriving its own enumeration of
"every session that exists" from a fresh `~/.claude/projects/` sweep.

This is additive infrastructure, not a required migration: `chapters
--all`/`timeline`/`trend`/`serve` keep working exactly as they do today,
via live sweeps of find_all_transcripts() - nothing here is wired into
them (see docs/architecture.md's "No cross-session store exists yet" note,
which this module starts to fill in without changing that behavior).

Why sqlite, not an append-only log (open question 2 in the issue): the
actual use case is date-range/initiative/activity-type querying across
sessions, which is what #3/#4 need - sqlite is the obvious fit for that,
an append-only log would just make every reader re-implement compaction.

Schema is deliberately minimal (open question left for later feature work
to extend, not to over-design up front): one `sessions` row per transcript
UUID (the existing stable identifier already used by `--session`/session
pinning/`sessions` - see open question 5, resolved as "don't invent a new
id"), keyed by that UUID, holding only what's cheap to maintain
incrementally: turn count, total cost, cached chapter count (if any), the
source transcript's own mtime, and our own last-synced wall-clock time.

Incremental sync (open question 4) is the actual point of this module:
`sync_history()` walks find_all_transcripts() and, for each transcript,
compares the file's current mtime against the mtime already stored for
that session. Unchanged sessions are skipped without even opening the
transcript - only a new or newly-modified transcript gets re-tailed and
re-written. This mirrors chapters.py's own frozen-prefix cache discipline,
just at the session-enumeration level instead of the per-session
turn-labeling level.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from work_ledger.chapters import cached_chapters
from work_ledger.transcript import TranscriptTailer, find_all_transcripts

CONFIG_DIR = Path.home() / ".config" / "work-ledger"
DB_PATH = CONFIG_DIR / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    transcript_uuid TEXT PRIMARY KEY,
    transcript_path TEXT NOT NULL,
    project         TEXT NOT NULL,
    transcript_mtime REAL NOT NULL,
    synced_at       TEXT NOT NULL,
    num_turns       INTEGER NOT NULL,
    cost_usd        REAL NOT NULL,
    num_chapters    INTEGER NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    """Open (creating if needed) the history database, with the `sessions`
    table present. CONFIG_DIR/DB_PATH are module attributes rather than
    inlined constants specifically so tests can monkeypatch both to a
    tmp_path location - same isolation pattern as limits.py's
    CONFIG_DIR/THRESHOLD_PATH (see tests/conftest.py's isolated_config_dir)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


@dataclass
class SessionRecord:
    transcript_uuid: str
    transcript_path: str
    project: str
    transcript_mtime: float
    synced_at: str
    num_turns: int
    cost_usd: float
    num_chapters: int


@dataclass
class SyncResult:
    total_transcripts: int
    updated: int
    unchanged: int

    @property
    def skipped(self) -> int:
        """Alias for `unchanged` - transcripts whose row was already
        current and so were never re-opened at all."""
        return self.unchanged


@dataclass
class HistoryStatus:
    db_path: Path
    row_count: int
    oldest_synced_at: str | None
    newest_synced_at: str | None


def _row_to_record(row: tuple) -> SessionRecord:
    return SessionRecord(
        transcript_uuid=row[0],
        transcript_path=row[1],
        project=row[2],
        transcript_mtime=row[3],
        synced_at=row[4],
        num_turns=row[5],
        cost_usd=row[6],
        num_chapters=row[7],
    )


def get_record(transcript_uuid: str) -> SessionRecord | None:
    with closing(_connect()) as conn:
        cur = conn.execute(
            "SELECT transcript_uuid, transcript_path, project, transcript_mtime, "
            "synced_at, num_turns, cost_usd, num_chapters FROM sessions WHERE transcript_uuid = ?",
            (transcript_uuid,),
        )
        row = cur.fetchone()
    return _row_to_record(row) if row else None


def all_records() -> list[SessionRecord]:
    """Every stored row, newest-synced first - not used by any command yet
    (that's #3's job), but exposed now so #3 doesn't need to add its own
    read path into this schema later."""
    with closing(_connect()) as conn:
        cur = conn.execute(
            "SELECT transcript_uuid, transcript_path, project, transcript_mtime, "
            "synced_at, num_turns, cost_usd, num_chapters FROM sessions "
            "ORDER BY synced_at DESC"
        )
        rows = cur.fetchall()
    return [_row_to_record(r) for r in rows]


def _sync_one(conn: sqlite3.Connection, path: Path, now_iso: str) -> None:
    tailer = TranscriptTailer(path)
    tailer.poll()
    turns = tailer.ordered_turns()
    num_chapters = len(cached_chapters(path))  # never triggers a Haiku pass - cache read only

    conn.execute(
        "INSERT INTO sessions (transcript_uuid, transcript_path, project, transcript_mtime, "
        "synced_at, num_turns, cost_usd, num_chapters) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(transcript_uuid) DO UPDATE SET "
        "transcript_path=excluded.transcript_path, project=excluded.project, "
        "transcript_mtime=excluded.transcript_mtime, synced_at=excluded.synced_at, "
        "num_turns=excluded.num_turns, cost_usd=excluded.cost_usd, "
        "num_chapters=excluded.num_chapters",
        (
            path.stem,
            str(path),
            path.parent.name,
            path.stat().st_mtime,
            now_iso,
            len(turns),
            tailer.total_cost_usd(),
            num_chapters,
        ),
    )


def sync_history(transcripts: list[Path] | None = None, now: datetime | None = None) -> SyncResult:
    """Idempotent incremental sync: for each transcript (default: every
    transcript find_all_transcripts() finds), only re-read and re-write its
    row if the transcript file's current mtime is newer than what's already
    stored. A transcript whose stored mtime is already current is skipped
    entirely - it's never opened, its row's `synced_at` doesn't change, and
    no cost is re-derived. This is the actual point of #42: a periodic or
    on-demand `history sync` should cost roughly "one stat() call per
    already-seen session" plus real work only for what's new or changed,
    not a full rescan of every transcript every time."""
    transcripts = find_all_transcripts() if transcripts is None else transcripts
    now_iso = (now or datetime.now(timezone.utc)).isoformat()

    updated = 0
    unchanged = 0
    with closing(_connect()) as conn:
        for path in transcripts:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue

            cur = conn.execute(
                "SELECT transcript_mtime FROM sessions WHERE transcript_uuid = ?", (path.stem,)
            )
            row = cur.fetchone()
            if row is not None and row[0] >= mtime:
                unchanged += 1
                continue

            _sync_one(conn, path, now_iso)
            updated += 1
        conn.commit()

    return SyncResult(total_transcripts=len(transcripts), updated=updated, unchanged=unchanged)


def get_status() -> HistoryStatus:
    with closing(_connect()) as conn:
        cur = conn.execute("SELECT COUNT(*), MIN(synced_at), MAX(synced_at) FROM sessions")
        row_count, oldest, newest = cur.fetchone()
    return HistoryStatus(
        db_path=DB_PATH, row_count=row_count or 0, oldest_synced_at=oldest, newest_synced_at=newest
    )
