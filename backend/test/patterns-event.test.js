// Route-level smoke tests for POST /patterns/:id/:event (api/patterns/[id]/[event].js)
// - #45's minimum bar: a route responds, and rejects malformed input.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadRouteWithFakeRedis, makeRes } = require("./helpers");

const ROUTE = "../api/patterns/[id]/[event].js";

test("rejects non-POST methods", async () => {
  const handler = loadRouteWithFakeRedis(ROUTE, {});
  const res = makeRes();
  await handler({ method: "GET", query: {} }, res);
  assert.equal(res.statusCode, 405);
});

test("rejects an invalid event name", async () => {
  const handler = loadRouteWithFakeRedis(ROUTE, {});
  const res = makeRes();
  await handler({ method: "POST", query: { id: "foo-bar", event: "bogus" }, body: {} }, res);
  assert.equal(res.statusCode, 400);
  assert.match(res.body.error, /invalid event/);
});

test("rejects an id that doesn't match the allowed pattern", async () => {
  const handler = loadRouteWithFakeRedis(ROUTE, {});
  const res = makeRes();
  await handler(
    { method: "POST", query: { id: "Not Valid!", event: "recommended" }, body: {} },
    res
  );
  assert.equal(res.statusCode, 400);
  assert.match(res.body.error, /invalid pattern id/);
});

test("increments the counter and responds 200 on a well-formed request", async () => {
  const calls = [];
  const fakeRedis = {
    async incr(key) {
      calls.push(["incr", key]);
      return 7;
    },
    async sadd(key, member) {
      calls.push(["sadd", key, member]);
    },
  };
  const handler = loadRouteWithFakeRedis(ROUTE, fakeRedis);
  const res = makeRes();
  await handler(
    { method: "POST", query: { id: "some-pattern", event: "used" }, body: {} },
    res
  );

  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { ok: true, count: 7 });
  assert.deepEqual(calls, [
    ["incr", "pattern:some-pattern:used_count"],
    ["sadd", "pattern_ids", "some-pattern"],
  ]);
});

test("dedupes a repeated (install_id, pattern, event) within the window without double-incrementing", async () => {
  const calls = [];
  const fakeRedis = {
    async set(key, value, opts) {
      calls.push(["set", key, value, opts]);
      return null; // Upstash returns null when NX fails - not the first time.
    },
    async incr() {
      throw new Error("incr should not be called on a deduped request");
    },
    async sadd() {
      throw new Error("sadd should not be called on a deduped request");
    },
  };
  const handler = loadRouteWithFakeRedis(ROUTE, fakeRedis);
  const res = makeRes();
  await handler(
    {
      method: "POST",
      query: { id: "some-pattern", event: "recommended" },
      body: { install_id: "abc123" },
    },
    res
  );

  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { ok: true, deduped: true });
});
