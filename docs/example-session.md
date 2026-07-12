# Example: `work-ledger chapters` on a real session

This is real output from `work-ledger chapters`, run against the actual
Claude Code session that was used to design and build the chaptering
feature itself (see `session-chaptering-design.md`) — not a synthetic demo.
It's checked in so the README/design doc can point at a concrete example of
what the tool produces, and so a future change to the output format has
something real to diff against.

Captured with a live Anthropic API key (Haiku 4.5), same session transcript
`work-ledger` was dogfooding on throughout that work.

## `work-ledger chapters`

```
Watching: ~/.claude/projects/-home-user-work-ledger/0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl
Chaptering makes a separate Claude API call (Haiku) to group prompts into
initiatives - distinct from the token-pricing estimate below, and billed to your
Anthropic API account, not your Claude Code session.


       work-ledger chapters — 0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Time     ┃ Prompt / task       ┃  Calls ┃   In tok ┃  Out tok ┃  Cost (est.) ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│          │ ▾ 1. Implement      │      5 │       78 │   39,761 │      $8.4794 │
│          │ chapters module     │        │          │          │        (43%) │
│          │     Build and test  │      1 │       58 │   29,506 │      $4.3362 │
│          │ chapters.py with    │        │          │          │              │
│          │ CLI integration     │        │          │          │              │
│          │     Configure API   │      4 │       20 │   10,255 │      $4.1432 │
│          │ credentials         │        │          │          │              │
├──────────┼─────────────────────┼────────┼──────────┼──────────┼──────────────┤
│          │ ▾ 2. Design         │      9 │       73 │   30,690 │      $5.9493 │
│          │ telemetry           │        │          │          │        (30%) │
│          │ separation          │        │          │          │              │
│          │ architecture        │        │          │          │              │
│          │     Plan refactor   │      1 │        2 │    3,786 │      $0.0982 │
│          │     Write and       │      2 │       37 │   15,376 │      $3.6394 │
│          │ iterate design doc  │        │          │          │              │
│          │     Resolve open    │      5 │       32 │   10,002 │      $2.0709 │
│          │ questions           │        │          │          │              │
│          │     Check review    │      1 │        2 │    1,526 │      $0.1407 │
│          │ status              │        │          │          │              │
├──────────┼─────────────────────┼────────┼──────────┼──────────┼──────────────┤
│          │ ▾ 3. Build token    │      3 │      428 │   56,712 │      $2.6180 │
│          │ usage tracking CLI  │        │          │          │        (13%) │
│          │     Design and      │      1 │      412 │   48,436 │      $2.1123 │
│          │ implement cost      │        │          │          │              │
│          │ breakdown           │        │          │          │              │
│          │     Open PR and set │      2 │       16 │    8,276 │      $0.5057 │
│          │ up review           │        │          │          │              │
│          │ automation          │        │          │          │              │
├──────────┼─────────────────────┼────────┼──────────┼──────────┼──────────────┤
│          │ ▾ 4. Display token  │      1 │       31 │   12,386 │      $2.5989 │
│          │ usage results       │        │          │          │        (13%) │
│          │     Show tracking   │      1 │       31 │   12,386 │      $2.5989 │
│          │ results             │        │          │          │              │
├──────────┼─────────────────────┼────────┼──────────┼──────────┼──────────────┤
│          │ ▾ 5. Create example │      1 │        2 │    1,515 │      $0.1697 │
│          │ session document    │        │          │          │         (1%) │
│          │     Write example   │      1 │        2 │    1,515 │      $0.1697 │
│          │ session to file     │        │          │          │              │
├──────────┼─────────────────────┼────────┼──────────┼──────────┼──────────────┤
│          │ TOTAL (shown)       │        │      612 │  141,064 │     $19.8153 │
│          │                     │        │          │          │ (some models │
│          │                     │        │          │          │    unpriced) │
└──────────┴─────────────────────┴────────┴──────────┴──────────┴──────────────┘
```

Five chapters, each a genuine step of the actual work: build the module,
design the split between telemetry and semantic layers, build the original
cost-tracking CLI (chronologically earliest, but cheap enough to sort last
by default), show the results, and write this example doc. Sorted by cost
descending, per the design's "here's what to cut" framing — note that
means chronological order and displayed order don't match, which is
intentional (see `session-chaptering-design.md`).

## `work-ledger chapters --json`

The same result in machine-readable form (`--only` and cross-session
tooling consume this shape):

```json
[
  {
    "title": "Implement chapters module",
    "cost_usd": 8.479378200000001,
    "sections": [
      {
        "title": "Build and test chapters.py with CLI integration",
        "prompt_ids": ["5cf1167e-4d70-4f99-841c-a7db3c005435"],
        "cost_usd": 4.3361909999999995
      },
      {
        "title": "Configure API credentials",
        "prompt_ids": [
          "bd27dbf0-4e4b-4030-aa8e-b96c1455b495",
          "cb40db01-ec02-4e47-8ef4-6de5e87ff8ae",
          "d450bbca-e03a-4959-ae57-11dcbc8fd4b3",
          "f617ea3f-bd2e-497d-a4d5-f404db4679b3"
        ],
        "cost_usd": 4.143187200000001
      }
    ]
  },
  {
    "title": "Design telemetry separation architecture",
    "cost_usd": 5.9493126,
    "sections": [
      {
        "title": "Plan refactor",
        "prompt_ids": ["ace554fa-cc0e-43e9-bbac-746fef9f9df9"],
        "cost_usd": 0.09823080000000001
      },
      {
        "title": "Write and iterate design doc",
        "prompt_ids": [
          "448ae5a6-de98-4cf2-8dc3-307b9cc257d2",
          "1c946f2c-a910-4318-9d77-7c0c15c4e107"
        ],
        "cost_usd": 3.6394256999999994
      },
      {
        "title": "Resolve open questions",
        "prompt_ids": [
          "2126f73b-9d83-4668-be58-ae4599821954",
          "7d145f98-deb1-412a-ab8f-3508034e6901",
          "67319930-56ec-44c7-91b9-8a2e331a3c4b",
          "bfce7748-d753-4f2f-83a6-ee9df734349f",
          "25d802d5-80b7-48c6-96fd-d42213d0e4b8"
        ],
        "cost_usd": 2.0709468
      },
      {
        "title": "Check review status",
        "prompt_ids": ["16aec775-e211-4154-9609-3342147d3df9"],
        "cost_usd": 0.1407093
      }
    ]
  },
  {
    "title": "Build token usage tracking CLI",
    "cost_usd": 2.6179764000000003,
    "sections": [
      {
        "title": "Design and implement cost breakdown",
        "prompt_ids": ["cdd6a46d-4c34-4719-b74b-60cee9ff80e3"],
        "cost_usd": 2.1123234
      },
      {
        "title": "Open PR and set up review automation",
        "prompt_ids": [
          "d446ef66-fe73-4953-82d7-c4002ec3bd7c",
          "44106488-b184-478e-bc02-c499772bb81b"
        ],
        "cost_usd": 0.505653
      }
    ]
  },
  {
    "title": "Display token usage results",
    "cost_usd": 2.5989342000000004,
    "sections": [
      {
        "title": "Show tracking results",
        "prompt_ids": ["c74bc891-f2fe-4f08-83fb-dc9883af797f"],
        "cost_usd": 2.5989342000000004
      }
    ]
  },
  {
    "title": "Create example session document",
    "cost_usd": 0.16969109999999998,
    "sections": [
      {
        "title": "Write example session to file",
        "prompt_ids": ["48ae4525-1630-4643-9de3-bbfb8e435cfe"],
        "cost_usd": 0.16969109999999998
      }
    ]
  }
]
```

## Notes on reading this example

- **Costs are live-recomputed, not frozen.** Chapter/section *assignment*
  (which `prompt_id`s belong to which chapter) is frozen once cached — but
  the dollar figures shown are always summed fresh from the current
  transcript's `Turn`/`Unit` data. If you re-run `chapters` on a turn
  that's still accumulating tool calls under the same prompt (a long
  response with many actions), its chapter's cost will grow between two
  runs even though its chapter assignment never changes. That's expected,
  not a bug — see "Architecture" in `session-chaptering-design.md`.
- **Costs use standard Sonnet 5 pricing** ($3/$15 per MTok), not the
  introductory rate ($2/$10 through 2026-08-31) — see `pricing.py` and the
  README's known-imprecision note. Figures here run a little high as a
  result.
- **The chaptering pass itself cost about $0.01–0.05** per incremental
  batch of new turns (Haiku 4.5, small input) — cheap enough that this
  whole 20-turn example cost a few cents to chapter, separate from the
  ~$19.82 of tracked session cost shown above.
