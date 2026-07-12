// Increments a pattern's recommended_count or used_count. See
// ../../../README.md for deploy steps, and ../../../../docs/
// pattern-library-design.md for the mechanism this serves.
//
// Deployed URL shape: POST /patterns/:id/:event (rewritten from this
// file's actual location - see ../../../vercel.json) - matches exactly
// what work_ledger/pattern_client.py already sends, so no client change
// was needed to add this backend.
const { Redis } = require("@upstash/redis");

// Checks both naming conventions since which one gets auto-injected
// depends on how the Upstash integration is connected in the Vercel
// dashboard (Storage tab) - verify the actual names under Settings ->
// Environment Variables after connecting it, per this project's README.
const redis = new Redis({
  url: process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN,
});

const VALID_EVENTS = new Set(["recommended", "used"]);
const ID_PATTERN = /^[a-z0-9-]+$/;

// Best-effort dedup window: the same install reporting the same event
// for the same pattern again within this many seconds doesn't count
// twice. Not a substitute for real abuse handling (see the design doc's
// decided-lower-priority-for-v1 note on this) - just cheap insurance
// against accidental double-sends (e.g. a retried request).
const DEDUP_WINDOW_S = 60;

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }

  const { id, event } = req.query;
  if (!VALID_EVENTS.has(event)) {
    res.status(400).json({ error: `invalid event: ${event}` });
    return;
  }
  if (typeof id !== "string" || !ID_PATTERN.test(id)) {
    res.status(400).json({ error: "invalid pattern id" });
    return;
  }

  const body = req.body || {};
  const installId = typeof body.install_id === "string" ? body.install_id : null;

  if (installId) {
    const dedupeKey = `seen:${installId}:${id}:${event}`;
    const firstTime = await redis.set(dedupeKey, "1", { nx: true, ex: DEDUP_WINDOW_S });
    if (!firstTime) {
      res.status(200).json({ ok: true, deduped: true });
      return;
    }
  }

  const countKey = `pattern:${id}:${event}_count`;
  const newCount = await redis.incr(countKey);
  // Tracked as a Set (not discovered via a KEYS scan, which is an
  // anti-pattern in Redis at any real scale) so counts.js can list every
  // known id cheaply.
  await redis.sadd("pattern_ids", id);

  res.status(200).json({ ok: true, count: newCount });
};
