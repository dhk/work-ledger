// Accepts code-review findings for later curation into pattern-library
// entries. See ../../docs/review-findings-harvesting-design.md.
//
// Unlike the counters route, this accepts free-text content, so it
// requires a real bearer-token credential (WORK_LEDGER_FINDINGS_TOKEN) -
// install_id here is still just a self-reported attribution tag, not
// auth, same as the counters route.
const { Redis } = require("@upstash/redis");

const redis = new Redis({
  url: process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN,
});

const MAX_FINDINGS_PER_SUBMISSION = 50;
const MAX_CATEGORY_LEN = 40;
const MAX_SUMMARY_LEN = 300;
const MAX_FAILURE_SCENARIO_LEN = 1000;
const MAX_FILE_LEN = 500;
const VALID_VERDICTS = new Set(["CONFIRMED", "PLAUSIBLE"]);
// Approximate trim on write - bounds growth on what's realistically a
// free/low-tier Upstash instance. Losing the oldest, already-curated-or-
// ignored findings once the stream is large is an acceptable tradeoff
// here, unlike the counters route which must never lose data.
const STREAM_MAXLEN = 10000;

function validateFinding(f) {
  if (!f || typeof f !== "object") return "each finding must be an object";
  if (!f.category || typeof f.category !== "string" || f.category.length > MAX_CATEGORY_LEN) {
    return `category must be a non-empty string up to ${MAX_CATEGORY_LEN} chars`;
  }
  if (!f.summary || typeof f.summary !== "string" || f.summary.length > MAX_SUMMARY_LEN) {
    return `summary must be a non-empty string up to ${MAX_SUMMARY_LEN} chars`;
  }
  if (
    !f.failure_scenario ||
    typeof f.failure_scenario !== "string" ||
    f.failure_scenario.length > MAX_FAILURE_SCENARIO_LEN
  ) {
    return `failure_scenario must be a non-empty string up to ${MAX_FAILURE_SCENARIO_LEN} chars`;
  }
  if (f.file != null && (typeof f.file !== "string" || f.file.length > MAX_FILE_LEN)) {
    return `file must be a string up to ${MAX_FILE_LEN} chars`;
  }
  if (f.line != null && !Number.isInteger(f.line)) {
    return "line must be an integer if present";
  }
  if (f.verdict != null && !VALID_VERDICTS.has(f.verdict)) {
    return `verdict must be one of ${[...VALID_VERDICTS].join(", ")} if present`;
  }
  return null;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }

  // The real gate: unlike the counters route, this accepts free-text
  // content, so a bearer token is required - a stranger who doesn't know
  // it gets rejected here, before anything touches Redis.
  const expectedToken = process.env.WORK_LEDGER_FINDINGS_TOKEN;
  const authHeader = req.headers.authorization || "";
  const providedToken = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : null;
  if (!expectedToken || !providedToken || providedToken !== expectedToken) {
    res.status(401).json({ error: "unauthorized" });
    return;
  }

  const body = req.body || {};
  const installId = typeof body.install_id === "string" ? body.install_id : null;
  const findings = Array.isArray(body.findings) ? body.findings : null;

  if (!findings || findings.length === 0) {
    res.status(400).json({ error: "findings must be a non-empty array" });
    return;
  }
  if (findings.length > MAX_FINDINGS_PER_SUBMISSION) {
    res.status(400).json({ error: `too many findings in one submission (max ${MAX_FINDINGS_PER_SUBMISSION})` });
    return;
  }
  for (const f of findings) {
    const err = validateFinding(f);
    if (err) {
      res.status(400).json({ error: err });
      return;
    }
  }

  const id = await redis.xadd(
    "findings",
    "*",
    {
      install_id: installId || "",
      submitted_at: new Date().toISOString(),
      findings: JSON.stringify(findings),
    },
    { trim: { type: "MAXLEN", threshold: STREAM_MAXLEN, comparison: "~" } }
  );

  res.status(200).json({ ok: true, id, count: findings.length });
};
