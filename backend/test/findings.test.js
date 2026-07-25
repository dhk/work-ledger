// Route-level smoke tests for POST /findings (api/findings.js) - the one
// route that accepts free text, so it's gated by a bearer token on top of
// the usual method/shape checks (#45).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadRouteWithFakeRedis, makeRes } = require("./helpers");

const ROUTE = "../api/findings.js";
const TOKEN = "test-token-value";

function withToken(fn) {
  return async () => {
    const prev = process.env.WORK_LEDGER_FINDINGS_TOKEN;
    process.env.WORK_LEDGER_FINDINGS_TOKEN = TOKEN;
    try {
      await fn();
    } finally {
      if (prev === undefined) delete process.env.WORK_LEDGER_FINDINGS_TOKEN;
      else process.env.WORK_LEDGER_FINDINGS_TOKEN = prev;
    }
  };
}

const validFinding = {
  category: "correctness",
  summary: "off-by-one in the retry loop",
  failure_scenario: "retries one fewer time than the configured max",
};

test("rejects non-POST methods", async () => {
  const handler = loadRouteWithFakeRedis(ROUTE, {});
  const res = makeRes();
  await handler({ method: "GET", headers: {} }, res);
  assert.equal(res.statusCode, 405);
});

test(
  "rejects a request with no bearer token, even before touching Redis",
  withToken(async () => {
    const handler = loadRouteWithFakeRedis(ROUTE, {
      async xadd() {
        throw new Error("xadd should not be called without a valid token");
      },
    });
    const res = makeRes();
    await handler({ method: "POST", headers: {}, body: { findings: [validFinding] } }, res);
    assert.equal(res.statusCode, 401);
  })
);

test(
  "rejects a request with the wrong bearer token",
  withToken(async () => {
    const handler = loadRouteWithFakeRedis(ROUTE, {});
    const res = makeRes();
    await handler(
      {
        method: "POST",
        headers: { authorization: "Bearer wrong-token" },
        body: { findings: [validFinding] },
      },
      res
    );
    assert.equal(res.statusCode, 401);
  })
);

test(
  "rejects an empty findings array",
  withToken(async () => {
    const handler = loadRouteWithFakeRedis(ROUTE, {});
    const res = makeRes();
    await handler(
      { method: "POST", headers: { authorization: `Bearer ${TOKEN}` }, body: { findings: [] } },
      res
    );
    assert.equal(res.statusCode, 400);
  })
);

test(
  "rejects a finding missing a required field",
  withToken(async () => {
    const handler = loadRouteWithFakeRedis(ROUTE, {});
    const res = makeRes();
    await handler(
      {
        method: "POST",
        headers: { authorization: `Bearer ${TOKEN}` },
        body: { findings: [{ summary: "no category or failure_scenario" }] },
      },
      res
    );
    assert.equal(res.statusCode, 400);
    assert.match(res.body.error, /category/);
  })
);

test(
  "accepts a well-formed submission and responds 200",
  withToken(async () => {
    const calls = [];
    const fakeRedis = {
      async xadd(stream, id, fields, opts) {
        calls.push([stream, id, fields, opts]);
        return "1234567890-0";
      },
    };
    const handler = loadRouteWithFakeRedis(ROUTE, fakeRedis);
    const res = makeRes();
    await handler(
      {
        method: "POST",
        headers: { authorization: `Bearer ${TOKEN}` },
        body: { install_id: "install-1", findings: [validFinding] },
      },
      res
    );

    assert.equal(res.statusCode, 200);
    assert.deepEqual(res.body, { ok: true, id: "1234567890-0", count: 1 });
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], "findings");
  })
);
