# work-ledger patterns backend

The counter backend for the shared pattern library (see
[`../docs/pattern-library-design.md`](../docs/pattern-library-design.md))
- the piece that didn't exist when that design shipped. Two routes:

- `POST /patterns/<id>/<event>` (`event` is `recommended` or `used`) -
  atomically increments that counter via Redis `INCR`.
- `GET /patterns/counts` - reads back every known pattern id's current
  counts, for verifying this works and as a source a future CLI
  enhancement could fetch live counts from.

This is a plain Vercel Serverless Functions project (no framework, no
frontend) backed by Upstash Redis, deployed as a **subdirectory of the
main `work-ledger` repo** rather than a separate repo, so it can share
this repo's PR/review flow without needing separate hosting for its own
source. Vercel supports pointing a project's Root Directory at a
subdirectory of a monorepo - that's what makes this work.

## Deploy

1. **Create the Vercel project.** In the Vercel dashboard: New Project →
   Import `dhk/work-ledger` → under "Root Directory," select `backend` →
   Deploy. (First deploy will succeed even without Redis configured yet -
   the routes will just error until the next step.)
2. **Add Redis.** In the project's Storage tab: Create Database → choose
   the Upstash/Redis option (branding has shifted over time - look for
   "Upstash" specifically, not a Postgres or Blob option) → connect it to
   this project. This should auto-populate environment variables -
   **check Settings → Environment Variables afterward** to see which
   names it actually used (`KV_REST_API_URL`/`KV_REST_API_TOKEN` or
   `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` are both handled
   by the code here, since which pair gets injected has varied by how
   the integration was connected).
3. **Redeploy** if the environment variables were added after the first
   deploy - Vercel requires a redeploy to pick up new env vars.
4. **Note the deployed URL** (e.g. `https://work-ledger-patterns-backend.vercel.app`).

## Verify it works

```sh
curl -X POST https://<your-deployment>.vercel.app/patterns/test-id/recommended \
  -H 'Content-Type: application/json' \
  -d '{"install_id": "manual-test"}'
# {"ok":true,"count":1}

curl https://<your-deployment>.vercel.app/patterns/counts
# {"test-id":{"recommended_count":1,"used_count":0}}
```

## Point work-ledger at it

```sh
export WORK_LEDGER_PATTERN_BACKEND_URL=https://<your-deployment>.vercel.app
work-ledger patterns enable
work-ledger recommend   # matching library entries now report real counts
```

## What this deliberately doesn't do

- **No content here.** Pattern content (`patterns/*.md`) stays in the
  main repo, PR-reviewed like code - this backend only stores two
  numbers per pattern id, nothing else.
- **No moderation/abuse tooling beyond a 60-second dedup window** per
  `(install_id, pattern_id, event)` - see the design doc's decided
  open question on why this is treated as lower-priority for v1 (every
  pattern is already manually reviewed before it's live; the only thing
  to abuse here is a counter on already-vetted content).
- **No auth on the increment routes** beyond the install-id dedup - the
  design doc's identity/auth decision was a per-install UUID for
  dedup/rate-limiting, not a real authentication system.
