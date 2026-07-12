// Reads current recommended/used counts for every pattern id seen so
// far. Useful for verifying the backend works, and as the source a
// future CLI enhancement could fetch live counts from (not built yet -
// today the CLI only shows the counts baked into patterns/*.md at
// content-review time, see docs/pattern-library-design.md's
// implementation notes).
const { Redis } = require("@upstash/redis");

const redis = new Redis({
  url: process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN,
});

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }

  const ids = await redis.smembers("pattern_ids");

  const counts = {};
  await Promise.all(
    ids.map(async (id) => {
      const [recommended, used] = await Promise.all([
        redis.get(`pattern:${id}:recommended_count`),
        redis.get(`pattern:${id}:used_count`),
      ]);
      counts[id] = {
        recommended_count: Number(recommended) || 0,
        used_count: Number(used) || 0,
      };
    })
  );

  res.status(200).json(counts);
};
