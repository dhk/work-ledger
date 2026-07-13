"""Client side of the pattern-library mechanism (see
docs/pattern-library-design.md): a per-install anonymous id, an explicit
opt-in flag, and best-effort reporting of the two counters
(report_recommended/report_used) to a configurable backend. Also the
client side of harvesting code-review findings (see docs/review-
findings-harvesting-design.md) into that same backend.

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

from work_ledger.patterns import ID_PATTERN

CONFIG_DIR = Path.home() / ".config" / "work-ledger"
INSTALL_ID_PATH = CONFIG_DIR / "install_id"
ENABLED_FLAG_PATH = CONFIG_DIR / "pattern_library_enabled"

BACKEND_URL_ENV = "WORK_LEDGER_PATTERN_BACKEND_URL"
REQUEST_TIMEOUT_S = 2.0
VALID_EVENTS = ("recommended", "used")

# Findings submission (docs/review-findings-harvesting-design.md). A
# separate credential from the counters route: install_id there is a
# self-reported dedup tag, not auth, and a free-text ingestion endpoint
# needs a real one - see that doc's "no auth on a free-text ingestion
# endpoint" discussion.
FINDINGS_TOKEN_ENV = "WORK_LEDGER_FINDINGS_TOKEN"
MAX_FINDINGS_PER_SUBMISSION = 50
MAX_CATEGORY_LEN = 40
MAX_SUMMARY_LEN = 300
MAX_FAILURE_SCENARIO_LEN = 1000
MAX_FILE_LEN = 500
VALID_VERDICTS = ("CONFIRMED", "PLAUSIBLE")


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
    the library isn't enabled, no backend is configured, the inputs don't
    match the documented id/event shape, or the request fails for any
    reason. Never raises.

    `pattern_id` reaches here from user input (--mark-used) and from
    arbitrary strings passed to the MCP tools, so it's validated against
    the same kebab-case slug rule patterns.py enforces before it's ever
    interpolated into a URL - an unvalidated value could otherwise contain
    "/" and route the request somewhere unintended."""
    if event not in VALID_EVENTS:
        return False
    if not ID_PATTERN.match(pattern_id):
        return False
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


class FindingValidationError(ValueError):
    """A submitted finding didn't match the shape submit_findings
    requires - mirrors the same limits backend/api/findings.js enforces,
    so a bad submission fails fast locally with a clear reason instead of
    a network round-trip to find out."""


def findings_token() -> str | None:
    return os.environ.get(FINDINGS_TOKEN_ENV) or None


def _validate_finding(finding: dict) -> None:
    category = finding.get("category")
    summary = finding.get("summary")
    failure_scenario = finding.get("failure_scenario")
    file = finding.get("file")
    line = finding.get("line")
    verdict = finding.get("verdict")

    if not category or not isinstance(category, str) or len(category) > MAX_CATEGORY_LEN:
        raise FindingValidationError(f"category must be a non-empty string up to {MAX_CATEGORY_LEN} chars")
    if not summary or not isinstance(summary, str) or len(summary) > MAX_SUMMARY_LEN:
        raise FindingValidationError(f"summary must be a non-empty string up to {MAX_SUMMARY_LEN} chars")
    if (
        not failure_scenario
        or not isinstance(failure_scenario, str)
        or len(failure_scenario) > MAX_FAILURE_SCENARIO_LEN
    ):
        raise FindingValidationError(
            f"failure_scenario must be a non-empty string up to {MAX_FAILURE_SCENARIO_LEN} chars"
        )
    if file is not None and (not isinstance(file, str) or len(file) > MAX_FILE_LEN):
        raise FindingValidationError(f"file must be a string up to {MAX_FILE_LEN} chars")
    if line is not None and not isinstance(line, int):
        raise FindingValidationError("line must be an integer if present")
    if verdict is not None and verdict not in VALID_VERDICTS:
        raise FindingValidationError(f"verdict must be one of {VALID_VERDICTS} if present")


def submit_findings(findings: list[dict]) -> tuple[bool, str]:
    """Best-effort submission of code-review findings for later curation
    into pattern-library entries (see docs/review-findings-harvesting-
    design.md). Validates client-side first, against the same limits the
    backend enforces - returns (sent, message), never raises.

    Only call this on explicit instruction, for a repo you actually have
    the right to share findings from - that instruction is the real
    safeguard here, not anything this function can check (see the design
    doc's "Whose codebase is this, actually" section)."""
    if not findings:
        return False, "no findings to submit"
    if len(findings) > MAX_FINDINGS_PER_SUBMISSION:
        return False, f"too many findings in one submission (max {MAX_FINDINGS_PER_SUBMISSION})"

    for f in findings:
        try:
            _validate_finding(f)
        except FindingValidationError as e:
            return False, str(e)

    if not is_enabled():
        return False, "pattern library isn't enabled (run: work-ledger patterns enable)"
    url = backend_url()
    if not url:
        return False, f"no backend configured (set {BACKEND_URL_ENV})"
    token = findings_token()
    if not token:
        return False, f"no findings token configured (set {FINDINGS_TOKEN_ENV})"

    body = json.dumps({"install_id": get_or_create_install_id(), "findings": findings}).encode("utf-8")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/findings",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as resp:
            if 200 <= resp.status < 300:
                return True, "submitted"
            return False, f"backend returned status {resp.status}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"request failed: {e}"
