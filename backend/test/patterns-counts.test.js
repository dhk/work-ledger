// Route-level smoke tests for GET /patterns/counts (api/patterns/counts.js).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadRouteWithFakeRedis, makeRes } = require("./helpers");

const ROUTE = "../api/patterns/counts.js";

test("rejects non-GET methods", async () => {
  const handler = loadRouteWithFakeRedis(ROUTE, {});
  const res = makeRes();
  await handler({ method: "POST" }, res);
  assert.equal(res.statusCode, 405);
});

test("responds 200 with recommended/used counts for every known pattern id", async () => {
  const fakeRedis = {
    async smembers() {
      return ["dataviz-skill", "unused-mcp-server"];
    },
    async get(key) {
      const values = {
        "pattern:dataviz-skill:recommended_count": "5",
        "pattern:dataviz-skill:used_count": "2",
        "pattern:unused-mcp-server:recommended_count": null,
        "pattern:unused-mcp-server:used_count": null,
      };
      return values[key];
    },
  };
  const handler = loadRouteWithFakeRedis(ROUTE, fakeRedis);
  const res = makeRes();
  await handler({ method: "GET" }, res);

  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, {
    "dataviz-skill": { recommended_count: 5, used_count: 2 },
    "unused-mcp-server": { recommended_count: 0, used_count: 0 },
  });
});
