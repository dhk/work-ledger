# Context Snapshot: review-findings-harvesting
Generated: 2026-07-13T02:37:40Z
Branch: claude/review-findings-implementation
Status: review
Description: Review-findings harvesting implemented (MCP tool + backend), PR #31 open, Copilot findings fixed

## Objective
Extend work-ledger's shared pattern-library mechanism ("the mother ship") so
code-review findings (from `/code-review`, `/review`, etc., in any Claude
Code session/repo/container) can be forwarded to the already-deployed
Vercel + Upstash Redis backend, giving the repo owner one place to spot
recurring findings across otherwise-siloed sessions and turn them into new
`patterns/*.md` entries by hand. Explicitly scoped as v1 = personal-only
harvesting (the repo owner's own sessions); v2 = opening submission to other
work-ledger users is deliberately deferred, not designed yet.

## Authoritative Inputs
- **User's original ask** (verbatim): "i want the MCP to be able to accept
  reivew outputs. The idea is that I can run it on a local repo, and then
  send it to the mcp serfver in the sky (us) with the info... let us find
  more pattenr library entries."
- **Explicit v1/v2 scoping decision** (user, verbatim): "design first - the
  idea is that I can use it first to easily harvest learnings from my
  various sessions in virtual containers on claude.ai/desktop; and then,
  subsequently, open it up to other people."
- **Design doc**: `docs/review-findings-harvesting-design.md` — written,
  reviewed by the user's own Claude Code session (4 comments), fixed, PR #29
  merged.
- **Critical correction from that review**: "personal-only" originally
  conflated *who submits* with *whose code is being reviewed* — fixed by
  adding a "Whose codebase is this, actually" section making the per-call
  human instruction to submit the real v1 safeguard, not a v2 problem.
- **Auth requirement from that review**: findings endpoint needed a real
  bearer-token credential (`WORK_LEDGER_FINDINGS_TOKEN`), distinct from the
  counters route's `install_id` (a dedup tag, never a credential).
- **Data model** (from the design doc, reusing `ReportFindings`'s own
  schema): `category`, `summary`, `failure_scenario`, `file`, `line`
  (optional), `verdict` (optional, CONFIRMED/PLAUSIBLE), wrapped in an
  envelope with `install_id` + server-assigned `submitted_at`.

## Technical Decisions

### Storage: Redis Stream, not List/Hash
**Decision**: `XADD findings MAXLEN ~ 10000 * ...` on the existing Upstash
Redis instance.
**Why**: append-only log meant to be read back in order later, unlike the
counters (which only need latest value). Approximate MAXLEN trim bounds
growth on a free/low-tier instance without a separate cleanup job.
**State**: implemented (`backend/api/findings.js`), verified via installed
`@upstash/redis` `.d.ts` for the exact `xadd(key, id, entries, opts)` shape.

### Auth: shared-secret bearer token, separate from install_id
**Decision**: `WORK_LEDGER_FINDINGS_TOKEN` env var, checked via
`Authorization: Bearer <token>` on the backend before touching Redis at all;
`install_id` stays a self-reported dedup tag only, same as the counters
route.
**Why**: unlike a counter increment, a free-text ingestion endpoint is a
materially bigger attack surface — anyone who found the URL could otherwise
POST unbounded arbitrary content.
**Alternatives rejected**: reusing `install_id` alone as the gate (that's
what the design doc's review flagged as insufficient).
**State**: implemented on both backend (`findings.js`) and client
(`pattern_client.submit_findings`).

### Client-side validation mirrors server-side validation exactly
**Decision**: `work_ledger/pattern_client.py`'s `_validate_finding()` enforces
the same field-length/type caps as `backend/api/findings.js`'s
`validateFinding()` (category ≤40 chars, summary ≤300, failure_scenario
≤1000, file ≤500, line integer, verdict in CONFIRMED/PLAUSIBLE, max 50
findings/submission).
**Why**: fail fast locally with a clear reason instead of a network
round-trip just to discover a malformed finding.
**State**: implemented + tested.

### submit_findings() must never raise (best-effort contract)
**Decision**: defensive checks added after Copilot review caught 3 gaps —
non-dict finding element, bool passed where an int `line` was expected (bool
is an int subclass in Python but fails the JS backend's
`Number.isInteger`), non-list `findings` argument.
**State**: fixed in commit `b63ce0c`, all 3 review threads resolved, tests
added (`test_submit_findings_rejects_non_list_input`,
`test_submit_findings_rejects_non_dict_finding`,
`test_submit_findings_rejects_bool_line`).

## Artifacts

### `backend/api/findings.js`
**File**: `backend/api/findings.js` (new)
**Purpose**: `POST /findings` route — bearer-token auth, per-field/count
validation, `XADD` to the `findings` stream trimmed to `MAXLEN ~ 10000`.
**Status**: completed, verified via `node --check` + standalone mocked
req/res smoke test (405/401/400 branches all confirmed to short-circuit
before any Redis call).

### `work_ledger/pattern_client.py`
**File**: `work_ledger/pattern_client.py`
**Purpose**: client-side `submit_findings(findings: list[dict]) -> tuple[bool, str]`
— validates, then POSTs to `{backend_url}/findings` with the bearer token;
best-effort, silent no-op if library disabled / no backend / no token.
**Status**: completed, hardened per Copilot review, tests passing.
**Key logic**:
```python
if not isinstance(findings, list) or not findings:
    return False, "no findings to submit"
...
if not isinstance(finding, dict):
    raise FindingValidationError("each finding must be an object")
...
if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
    raise FindingValidationError("line must be an integer if present")
```

### `work_ledger/mcp_server.py`
**File**: `work_ledger/mcp_server.py`
**Purpose**: new `submit_review_findings(findings: list[dict]) -> str` MCP
tool alongside existing `list_patterns`/`report_recommended`/`report_used`;
thin wrapper calling `pattern_client.submit_findings()`.
**Status**: completed.

### `backend/vercel.json`
**File**: `backend/vercel.json`
**Purpose**: rewrite `/findings` → `/api/findings` so the deployed URL shape
matches what the Python client sends.
**Status**: completed.

### Tests
**Files**: `tests/test_pattern_client.py` (+~165 lines), `tests/test_mcp_server.py`
(updated tool-registration set to include `submit_review_findings`).
**Status**: completed — 108 tests passing total.

### Docs
**Files**: `README.md` ("Pattern library" section — new `submit_review_findings`
bullet + env var docs), `backend/README.md` (new `/findings` route + "Findings
harvesting setup" section with curl example), `docs/review-findings-harvesting-design.md`
(status line updated to "implemented"), `docs/pattern-library-design.md`
(cross-reference updated from "not yet built" to "implemented").
**Status**: completed.

## Validation
- `python -m compileall -q work_ledger` — clean.
- `pytest` — 108 passed (was 105 before the Copilot-review hardening commit).
- `node --check backend/api/findings.js` — clean.
- `node -e "JSON.parse(require('fs').readFileSync('backend/vercel.json'))"` — valid JSON.
- Standalone Node script mocking req/res exercised all of `findings.js`'s
  validation branches (405 wrong method, 401 missing/wrong token, 400 empty/
  over-limit/invalid-field findings) without needing live Redis credentials.
- Standalone Python REPL smoke test exercised all of `submit_findings()`'s
  no-op paths (disabled, no backend, no token) plus a real (failing, since
  the sandbox proxy blocks `*.vercel.app`) network attempt to confirm the
  request actually gets built and sent.

## Warnings
- ⚠️ **Two Claude Code sessions have operated concurrently on this repo**
  before (discovered via a reverted-commit collision on an earlier PR branch,
  and a separate session's PR #24 "skill-rot" design + issues #22/#23). User
  said "ignore it" re: PR #24 — do not touch PR #24 or its related issues
  unless the user raises it again.
- ⚠️ **Sandbox networking**: outbound HTTPS goes through a policy-enforcing
  proxy; `*.vercel.app` is not on the egress allowlist (confirmed via
  `curl "$HTTPS_PROXY/__agentproxy/status"`). Any live verification against
  the deployed backend (e.g. testing `WORK_LEDGER_FINDINGS_TOKEN` end-to-end)
  has to be run by the user themselves, not from this environment. Per
  `/root/.ccr/README.md`, policy denials must be reported, never routed
  around.
- ⚠️ **`WORK_LEDGER_FINDINGS_TOKEN` is not yet actually set** on the live
  Vercel deployment (as of this snapshot) — the code paths are built and
  tested, but the user still needs to: generate a token, set it in Vercel's
  env vars, redeploy, and set the same value wherever `work-ledger-mcp` runs.
  See `backend/README.md`'s "Findings harvesting setup" section for the
  exact steps.
- ⚠️ A `send_later` self-check-in on PR #31 was attempted and **denied by the
  user** — do not re-attempt automatic scheduled check-ins on this PR unless
  asked; rely on webhook-delivered PR activity events instead (already
  subscribed via `subscribe_pr_activity`).

## Known Gaps & Limitations
- ❌ **No retry-dedup on findings submission** — acknowledged, not solved, in
  the design doc. A client-side retry would silently double-append to the
  Redis stream. Low-stakes since curation is manual (a human will notice
  near-duplicates). Proposed follow-up (not built): a client-generated
  idempotency key checked against a short-TTL marker key, same pattern as
  the counters route's existing dedup.
- ❌ **No `GET /findings` read endpoint** — v1 curation happens by browsing
  the Upstash console directly. A repo-owner-only, token-gated read route is
  reasonable v1.5 work, not built.
- ⚠️ **v2 (opening submission to other users) is fully unscoped** — needs its
  own consent gate (separate from `patterns enable`), a redaction/review step
  before findings are visible to anyone but the repo owner, and real abuse/
  volume handling. None of this is designed, per explicit user instruction to
  defer it.
- ⚠️ **Packaging gap (pre-existing, unrelated to this feature but still open)**:
  `patterns/*.md` content lives at the repo root, not inside the installable
  `work_ledger` package — a real `pip install work-ledger` from PyPI would not
  include it. Documented in `docs/pattern-library-design.md`, not fixed.

## Out of Scope
- Automatic pattern-entry generation from submitted findings (mining/
  clustering/LLM summarization across submissions) — explicitly deferred,
  needs volume first.
- Any automatic redaction/anonymization pipeline for finding text — explicitly
  deferred; the per-call human instruction to submit is the v1 safeguard
  instead (see design doc's "Whose codebase is this, actually" section).
- SHA-pinning GitHub Actions (`actions/checkout`, `actions/setup-python`) in
  `.github/workflows/ci.yml` — considered during the CI-wiring PR, explicitly
  **not** applied (couldn't verify real commit SHAs from this sandboxed
  environment; a wrong pin would silently break CI, judged worse than not
  pinning). Separate ticket if the user wants it revisited.

## Next Actions
- [ ] Monitor PR #31 (dhk/work-ledger) for merge — currently open, 3 Copilot
      review comments fixed and resolved (commit `b63ce0c` pushed), no
      outstanding review threads as of this snapshot. Already subscribed to
      PR activity events for this session.
- [ ] Once merged: user needs to actually set `WORK_LEDGER_FINDINGS_TOKEN` on
      the live Vercel deployment (see `backend/README.md`) before
      `submit_review_findings` can do anything beyond a documented no-op.
- [ ] BLOCKED (not urgent): v2 (opening findings harvesting to other
      work-ledger users) — deliberately deferred, no design work started.

---
*Resume:* load this file
