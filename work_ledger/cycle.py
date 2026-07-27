"""The "cycle"/upgrade path `CLAUDE.md`'s "CLI/MCP command conventions"
section requires - issue #73, see docs/cycle-command-design.md for the
full design.

Two variants, detected automatically rather than asked for:

- **Local cycle** (editable clone, `pip install -e .`): `git pull` in the
  repo root.
- **Cycle from last published** (pipx/uv tool/pip install): upgrade via
  whichever installer actually put this install where it is.

Deliberately does NOT try to detect/kill/restart a running `work-ledger
serve` process - see the design doc's Non-goals. It only checks whether
something is listening on `serve`'s port and tells the person to handle
that themselves; it never sends a process a signal it wasn't asked to.
"""

import json
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PACKAGE_NAME = "work-ledger"
DEFAULT_SERVE_PORT = 8765

EDITABLE = "editable"
PUBLISHED_PYPI = "published-pypi"
PUBLISHED_GIT = "published-git"


@dataclass
class InstallInfo:
    mode: str  # EDITABLE | PUBLISHED_PYPI | PUBLISHED_GIT
    version: str
    repo_root: Path | None = None  # only for EDITABLE
    git_url: str | None = None  # only for PUBLISHED_GIT - the original git+... URL


def _git_root_fallback() -> Path | None:
    """Fallback for editable installs that predate PEP 660 (pip/setuptools
    still write a plain .egg-info with no direct_url.json for some
    `pip install -e .` paths) - if this package's own source lives inside
    a git checkout, treat that as an editable install too rather than
    misreporting it as a published one. Walks up from work_ledger's own
    package directory looking for a .git directory."""
    import work_ledger

    candidate = Path(work_ledger.__file__).resolve().parent
    for parent in [candidate, *candidate.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def detect_install_mode() -> InstallInfo:
    """Read PEP 610's direct_url.json (written by pip/pipx/uv on install)
    to tell an editable checkout apart from a published install, and a
    published-from-a-git-ref install apart from a published-from-PyPI one.
    Falls back to `_git_root_fallback` for editable installs old enough
    not to have direct_url.json at all - only once that fallback also
    finds nothing is this reported as a normal index install, the common
    case for anyone who ran `pip install work-ledger`/`pipx install
    work-ledger` once a real release exists."""
    dist = metadata.distribution(PACKAGE_NAME)
    version = dist.version

    raw = dist.read_text("direct_url.json")
    if not raw:
        fallback_root = _git_root_fallback()
        if fallback_root is not None:
            return InstallInfo(mode=EDITABLE, version=version, repo_root=fallback_root)
        return InstallInfo(mode=PUBLISHED_PYPI, version=version)

    data = json.loads(raw)
    dir_info = data.get("dir_info", {})
    if dir_info.get("editable"):
        url = data.get("url", "")
        # file:///abs/path -> /abs/path - direct_url.json always writes an
        # absolute file:// URL for an editable install, never a relative one.
        repo_root = Path(url[len("file://") :]) if url.startswith("file://") else None
        return InstallInfo(mode=EDITABLE, version=version, repo_root=repo_root)

    vcs_info = data.get("vcs_info")
    if vcs_info:
        return InstallInfo(mode=PUBLISHED_GIT, version=version, git_url=data.get("url"))

    return InstallInfo(mode=PUBLISHED_PYPI, version=version)


def detect_installer() -> str | None:
    """Best-effort guess at which tool (pipx/uv tool/pip) manages this
    install, from `sys.executable`'s path - pipx and uv tool each run
    installed packages from their own dedicated venv, whose path reliably
    contains their name. Returns None (not a guess) when neither pattern
    matches, so callers fall back to a plain `pip install --upgrade`
    suggestion rather than running a command that might be wrong."""
    exe = sys.executable.replace("\\", "/")
    if "/pipx/" in exe:
        return "pipx"
    if "/uv/tools/" in exe or "/uv/tool/" in exe:
        return "uv"
    return None


def upgrade_command(install: InstallInfo) -> list[str]:
    """The command `cycle` would run (or suggest) to upgrade this
    install - never called for an EDITABLE install, which uses `git pull`
    instead (see cycle_report/run_cycle)."""
    installer = detect_installer()
    target = install.git_url if install.mode == PUBLISHED_GIT else PACKAGE_NAME

    if installer == "pipx":
        return ["pipx", "upgrade", PACKAGE_NAME] if install.mode == PUBLISHED_PYPI else [
            "pipx", "install", "--force", target
        ]
    if installer == "uv":
        return ["uv", "tool", "upgrade", PACKAGE_NAME] if install.mode == PUBLISHED_PYPI else [
            "uv", "tool", "install", "--force", target
        ]
    return [sys.executable, "-m", "pip", "install", "--upgrade", target]


def is_port_in_use(port: int = DEFAULT_SERVE_PORT, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    """Best-effort check for "something is listening on this port," used
    to warn that a `work-ledger serve` instance looks like it's running -
    never a claim about which process it is, and never a basis for
    signaling anything. A successful connect is the only thing checked;
    refused/timed-out connections are treated as "nothing there"."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def _repo_root_or_raise(install: InstallInfo) -> Path:
    if install.repo_root is None or not (install.repo_root / ".git").exists():
        raise CycleError(
            f"detected an editable install but couldn't find a .git directory at "
            f"{install.repo_root or '(unknown path)'} - run `git pull` yourself from your "
            "actual clone."
        )
    return install.repo_root


class CycleError(Exception):
    """Raised for a condition `run_cycle` can't safely proceed past -
    always caught by the CLI layer and printed as a clear message, never
    an unhandled traceback."""


@dataclass
class CycleReport:
    """What `run_cycle`/`--check-status` found and (if not check_status)
    did. `serve_port_in_use` is a warning, not blocking - the person
    decides whether to stop it themselves."""

    install: InstallInfo
    serve_port_in_use: bool
    serve_port: int
    # Populated only when an actual cycle (not --check-status) ran:
    action: str | None = None  # e.g. "git pull", "pipx upgrade work-ledger"
    before: str | None = None  # commit SHA or version before
    after: str | None = None  # commit SHA or version after
    changed: bool = False


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def check_status(port: int = DEFAULT_SERVE_PORT) -> CycleReport:
    """The --check-status path: every detection step, no changes made."""
    install = detect_install_mode()
    return CycleReport(install=install, serve_port_in_use=is_port_in_use(port), serve_port=port)


def run_cycle(port: int = DEFAULT_SERVE_PORT) -> CycleReport:
    """Detect the install mode and actually run the matching upgrade step.
    Raises CycleError for anything that stops it from proceeding safely
    (uncommitted local changes, a missing git repo, a missing installer
    command) - the CLI layer turns that into a clear printed message, not
    a crash."""
    install = detect_install_mode()
    serve_running = is_port_in_use(port)

    if install.mode == EDITABLE:
        repo_root = _repo_root_or_raise(install)
        status = _git("status", "--porcelain", cwd=repo_root)
        if status:
            raise CycleError(
                f"{repo_root} has uncommitted changes - commit or stash them first, then "
                "re-run `work-ledger cycle` (a `git pull` here could otherwise fail or, in "
                "rarer cases, produce a confusing merge state)."
            )
        before = _git("rev-parse", "HEAD", cwd=repo_root)
        _git("pull", cwd=repo_root)
        after = _git("rev-parse", "HEAD", cwd=repo_root)
        return CycleReport(
            install=install,
            serve_port_in_use=serve_running,
            serve_port=port,
            action="git pull",
            before=before,
            after=after,
            changed=before != after,
        )

    command = upgrade_command(install)
    if shutil.which(command[0]) is None:
        raise CycleError(
            f"this looks like a {detect_installer() or 'pip'}-managed install, but "
            f"`{command[0]}` isn't on PATH - run `{' '.join(command)}` yourself once it is."
        )
    before = install.version
    subprocess.run(command, check=True)
    after = detect_install_mode().version
    return CycleReport(
        install=install,
        serve_port_in_use=serve_running,
        serve_port=port,
        action=" ".join(command),
        before=before,
        after=after,
        changed=before != after,
    )
