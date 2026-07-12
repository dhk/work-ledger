"""Client side of the pattern-library mechanism (see
docs/pattern-library-design.md): a per-install anonymous id, an explicit
opt-in flag, and best-effort reporting of the two counters
(report_recommended/report_used) to a configurable backend.

Opt-in, not default-on: nothing in this module makes a network call
unless `is_enabled()` is true. Every network call is best-effort and
swallows its own failures - a report call must never crash or delay
`recommend`, exactly like `chapters` never lets a chaptering-call failure
take down the rest of the command.

Honest scoping note: there is no publicly hosted backend run by this
project (see docs/pattern-library-design.md's hosting section) - set
WORK_LEDGER_PATTERN_BACKEND_URL to your own deployed instance to actually
see counters update. Without it, opting in still works locally (the
install id gets created, `recommend` still shows matching library
content), it just has nowhere to report to - report_event() is a no-op
in that case, not an error.
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "work-ledger"
INSTALL_ID_PATH = CONFIG_DIR / "install_id"
ENABLED_FLAG_PATH = CONFIG_DIR / "pattern_library_enabled"

BACKEND_URL_ENV = "WORK_LEDGER_PATTERN_BACKEND_URL"
REQUEST_TIMEOUT_S = 2.0


def get_or_create_install_id() -> str:
    """A random per-install identifier - no PII, never tied to a person.
    Exists only so a backend can dedup repeated reports from the same
    install (see docs/pattern-library-design.md, decided open question on
    identity/auth)."""
    if INSTALL_ID_PATH.exists():
        try:
            existing = INSTALL_ID_PATH.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except OSError:
            pass
    new_id = str(uuid.uuid4())
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        INSTALL_ID_PATH.write_text(new_id, encoding="utf-8")
    except OSError:
        pass
    return new_id


def is_enabled() -> bool:
    return ENABLED_FLAG_PATH.exists()


def enable() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENABLED_FLAG_PATH.write_text("", encoding="utf-8")
    get_or_create_install_id()


def disable() -> None:
    try:
        ENABLED_FLAG_PATH.unlink()
    except FileNotFoundError:
        pass


def backend_url() -> str | None:
    return os.environ.get(BACKEND_URL_ENV) or None


def report_event(pattern_id: str, event: str) -> bool:
    """Best-effort report of `event` ("recommended" or "used") for
    `pattern_id`. Returns whether it was actually sent - False whenever
    the library isn't enabled, no backend is configured, or the request
    fails for any reason. Never raises."""
    if not is_enabled():
        return False
    url = backend_url()
    if not url:
        return False

    body = json.dumps({"install_id": get_or_create_install_id()}).encode("utf-8")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/patterns/{pattern_id}/{event}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False
