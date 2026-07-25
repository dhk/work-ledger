// Shared test helpers for backend/api/*.js route smoke tests (#45). No test
// framework or mocking library is added on top of what package.json already
// declares - `node --test` (built into the Node versions this repo already
// requires) plus a small require.cache swap for `@upstash/redis` is enough.
//
// Every route file does `const { Redis } = require("@upstash/redis")` and
// `new Redis({...})` at module load time. Since none of these routes accept
// an injected client, `loadRouteWithFakeRedis` intercepts the require by
// pre-populating require.cache for @upstash/redis's resolved path with a
// fake module, then requiring the route file fresh so it picks up the fake.
// Both cache entries are cleared afterward so later tests (with a different
// fake) get a clean load.
"use strict";

const path = require("node:path");

function loadRouteWithFakeRedis(routeRelPathFromHere, fakeRedisImpl) {
  const upstashPath = require.resolve("@upstash/redis");
  const routePath = require.resolve(path.join(__dirname, routeRelPathFromHere));

  delete require.cache[upstashPath];
  delete require.cache[routePath];

  require.cache[upstashPath] = {
    id: upstashPath,
    filename: upstashPath,
    loaded: true,
    exports: {
      // Route files call `new Redis({...})` - a constructor that explicitly
      // returns an object makes `new` yield that object instead of `this`.
      Redis: function FakeRedis() {
        return fakeRedisImpl;
      },
    },
  };

  const handler = require(routePath);

  // Don't leak the fake into any test that forgets to call this helper -
  // each test gets its own fresh require of both modules.
  delete require.cache[routePath];
  delete require.cache[upstashPath];

  return handler;
}

function makeRes() {
  const res = {
    statusCode: null,
    body: null,
    status(code) {
      res.statusCode = code;
      return res;
    },
    json(obj) {
      res.body = obj;
      return res;
    },
  };
  return res;
}

module.exports = { loadRouteWithFakeRedis, makeRes };
