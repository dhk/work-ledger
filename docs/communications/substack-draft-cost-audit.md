## I ran a cost audit on a week of my own AI coding sessions. Here's what it found.

If you use Claude Code (or any agentic coding tool) regularly, you're
generating a paper trail without realizing it — every prompt, every tool
call, every token in and out is sitting in a local transcript file on your
machine. Nobody looks at it. Which is a shame, because it's basically a
receipt for how you actually spent your time and money this week, not how
you *think* you spent it.

I built a small CLI ([work-ledger](https://pypi.org/project/work-ledger/))
that reads those transcripts and groups them into "chapters" — the actual
initiatives you worked on, not just a flat list of prompts. Below is an
illustrative week (numbers constructed for this post, not a real session)
that shows the kind of thing this view tends to surface.

![Cost by initiative — a week of synthetic session data, chaptered and sorted by spend](chapters-synthetic.png)

### The debugging spiral (37% of the week's spend)

One chapter — "debug intermittent payment-retry test failures" — ate more
than a third of the week on its own. Not because the bug was uniquely
hard, but because the middle section, "try four different fixes for the
race condition," took *14 back-and-forth calls* before landing on the one
that stuck.

That's the pattern worth watching for: cost concentrated in a single
section of a single chapter, with a high call count and no early exit.
It's the signature of trial-and-error without a hypothesis — poking at the
code instead of reasoning about it first. The fix isn't "stop debugging
with AI," it's noticing the spiral by call three or four and stepping back
to actually root-cause before trying fix number five.

### The refactor that should've been a script (22%)

Second-biggest chapter: converting a legacy switch-statement dispatcher to
a strategy pattern, one call site at a time, across 12 separate calls.
Mechanical, repetitive, and — in hindsight — exactly the kind of transform
a single well-scoped prompt (or an actual codemod) handles in one pass
instead of twelve. Paying per-call-site instead of per-transform is an
easy way to 10x the cost of a refactor that was never actually hard, just
repetitive.

### The chapter that reveals a planning gap (9%)

"Rebuild onboarding email template (second attempt)" is small in dollar
terms but interesting in shape: a full first pass, discarded, followed by
a full second pass, because of a wrong assumption about which templating
engine was in use. That's not a debugging cost — it's a *scoping* cost.
Thirty seconds of "which templating engine are we actually using" up front
would have made the first section unnecessary entirely.

### The contrast case: money well spent (18%)

Not everything expensive is a red flag. "Investigate and fix Stripe
webhook duplicate-charge bug" cost nearly as much as the debugging
spiral above it, but the shape is completely different: reproduce, root
cause, ship fix — three clean sections, no backtracking. Same dollar
range, opposite story. The chart alone can't tell you which is which; you
have to look at the *shape* of the spend, not just the size.

### The pile that never got sorted (5%)

"Unsorted" is its own small flag. These are turns that didn't cluster
into any initiative — sometimes genuinely unrelated one-off questions,
sometimes fragments of a side quest that never got followed up on. Worth
a glance every so often, if only to make sure nothing important is
quietly living there.

---

**The takeaway isn't "spend less on AI."** It's that a week of agentic
coding produces enough exhaust to answer a much more useful question than
"how much did this cost": *where did the cost concentrate, and does the
shape of that spend match the value you got out of it?* A debugging
spiral and a clean investigation can cost the same amount and mean
completely different things — you only find out by looking.

*(work-ledger is open source and runs entirely on your local transcripts —
nothing is uploaded. `pip install work-ledger`, then `work-ledger chapters
--report` on your own sessions.)*
