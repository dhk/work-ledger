---
id: outlier-chapter-cost-review
title: Review an outlier-cost chapter before assuming it was necessary
category: cost
maps_to: outlier-chapter-cost
recommended_count: 0
used_count: 0
---

## Pattern

One chapter in a session costs several times the session's own median
chapter cost, without a corresponding jump in how much real work it
covers - the same signal `recommend`'s outlier-chapter-cost rule already
flags structurally.

## Use Case

A debugging or review chapter that involved several rounds of a subagent
or a large tool re-run (e.g. re-reading the same large files, or a
review pass that iterated more times than the actual defect count would
suggest) ends up costing multiples of a comparably-scoped chapter earlier
in the same session.

## Diagnosis

An outlier chapter is often not "harder work," it's **unbounded
iteration** - a loop of tool calls that kept going past the point where
the first pass or two would have sufficed, usually because there was no
explicit stopping condition or scope boundary given for that piece of
work. The cost signal is a symptom; the root cause is usually a fuzzy or
open-ended instruction that let the work expand.

## Fix

Before treating an outlier chapter's cost as "that's just what it took,"
run `work-ledger chapters --only "<title>" --detail` and skim the actual
calls behind it. Look specifically for: the same file read or the same
subagent dispatched more than 2-3 times, or a review/fix loop that
repeated more rounds than the number of real findings would justify. If
you find that pattern, the fix isn't retroactive - it's giving the next
similarly-scoped task an explicit boundary up front (e.g. "check these
3 things and stop" rather than open-ended "review this").
