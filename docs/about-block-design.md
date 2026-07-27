# Design: The "About" Block

Status: decided and implemented (issue #75) — `work_ledger/about.py` plus
all four surfaces (`work-ledger about`, `work-ledger-mcp`'s `about` tool,
`serve`'s pages, every generated report's footer) are shipped; see the
"Open questions" section below for how the two open questions resolved.
Author: written by Claude, from a conversation with the repo owner.
Related: issue #75, `CLAUDE.md`'s "CLI/MCP command conventions" section
(the "About" block requirement this implements), issue #73/`cycle.py`
(the sibling requirement in the same section, and the install-mode
detection this reuses).

## Problem

`CLAUDE.md` already commits this project to a rule: every user-facing
surface (every CLI command, the MCP server, the web UI, any generated
report) should be able to show an about block with a fixed set of
fields - short description, version, last update date/time, commit head
if known, and author/repo attribution. Nothing implements this today,
the same kind of documented-but-unbuilt gap #73 (`work-ledger cycle`)
just closed for the upgrade-path requirement in the same `CLAUDE.md`
section.

## Goals

- One shared computation, `work_ledger/about.py`, reused by every
  surface rather than four separate implementations that could drift.
- Exactly the fields `CLAUDE.md` specifies, no more: description,
  version, last update date/time, commit head (if known - never
  guessed), author/repo.
- Degrade cleanly for a published (non-git) install: no commit head, no
  "last updated from git log" date - fall back to something honest
  (package install/file mtime), not a fabricated commit reference.

## Non-goals (for this pass)

- **A general telemetry/analytics surface.** This is static metadata
  about the running code, not usage data - unrelated to, and not a
  reason to touch, `pattern_client.py`'s opt-in counters.
- **Auto-refreshing the about block from a remote source** (e.g.
  checking PyPI for whether a newer version exists). That's `cycle
  --check-status`'s job (issue #73), not this one - about answers "what
  is this," not "is this current."

## Architecture

### `work_ledger/about.py`

```python
@dataclass
class AboutInfo:
    description: str
    version: str
    last_updated: str        # ISO date/time, best available source
    commit: str | None       # short SHA, only when resolvable
    author_email: str
    author_url: str
    repo_url: str

def get_about_info() -> AboutInfo: ...
```

- **description**: a fixed one-line string constant.
- **version**: `importlib.metadata.version("work-ledger")` - same
  source `pyproject.toml`'s `[project] version` publishes.
- **commit / last_updated**: reuses `cycle.detect_install_mode()` (#73)
  to check whether this is an editable/git-backed install.
  - Editable (git repo root known): `git rev-parse --short HEAD` for
    commit, `git log -1 --format=%cI` for last_updated (the last
    commit's own timestamp - reflects the actual code running, not
    "when was this looked at").
  - Published, no resolvable repo root: `commit = None`; `last_updated`
    falls back to the installed package's own file mtime (still
    honest - "when this file landed on disk" - not a guess dressed up
    as a git fact).
  - Any git command failing for any reason (git not installed, not
    actually a repo despite the install-mode heuristic saying so)
    degrades the same way as the "published, no repo root" case rather
    than raising - this is metadata, never worth crashing a command
    over.
- **author_email/author_url/repo_url**: fixed constants
  (`davehk@gmail.com`, `www.dhk.io`,
  `https://github.com/dhk/work-ledger`), matching `CLAUDE.md`'s "About"
  block section verbatim.

### Four surfaces

1. **`work-ledger about`** - new subcommand, Rich terminal output.
2. **`work-ledger-mcp`** - a new `about` tool alongside the existing
   pattern-library tools, returning the same fields as structured
   content.
3. **`work-ledger serve`** - a small footer rendered on every page
   (landing + session detail), reusing `report.py`'s shared style block
   so it looks consistent with the rest of the UI.
4. **Generated reports** (`chapters --report`/`activity --report`/etc.,
   all built through `report.py`'s shared HTML rendering) - the same
   small footer as `serve`'s, so a screenshot or exported HTML file
   carries its own provenance.

## Migration/compatibility

Purely additive - a new subcommand, a new MCP tool, and a footer
appended to existing HTML output. No existing command's behavior or
output shape changes beyond that added footer.

## Open questions

1. Exact footer placement/styling for `serve`/reports - **resolved**:
   `report.py` grew one shared `_footer_html()` helper (calling
   `about.get_about_info()` once per render), inserted just before each
   `build_*` function's closing `</div></div>`, right after its existing
   `<p class="footnote">` explanation. Rendered as a single small, muted
   line (`.ledger-footer` - 11px, `--text-muted`, 0.8 opacity, reusing
   `_style_block()`'s existing CSS variables so light/dark mode Just
   Work) reading "work-ledger v{version} · {commit or last_updated date}
   · github.com/dhk/work-ledger" - deliberately subordinate to the
   report's own footnote, not competing with it visually. `serve`'s pages
   needed no separate footer logic: `server.py` renders exclusively
   through `report.py`'s `build_sessions_index_html`/
   `build_session_detail_html`, so they picked up the footer for free.
2. Whether `work-ledger about --json` is worth adding - **resolved: yes**,
   built alongside the terminal view, mirroring every other command's
   `--json` convention (`chapters --json`, `sessions --json`, etc.) rather
   than being the one command that doesn't offer it.
