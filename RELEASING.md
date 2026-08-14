# Releasing

What `pip install work-ledger` gives a stranger is whatever was last
published — not what's on `main`. Those two drifted 97 commits and twelve
subcommands apart once already ([#103](https://github.com/dhk/work-ledger/issues/103)),
so this file exists to make the gap easy to close and hard to forget.

## The process

Releasing is one manual action, gated by automated checks.

1. **Bump the version** in `pyproject.toml`.
   `MAJOR.MINOR.PATCH`, still `0.x`: new commands or meaningful new
   behavior bump the minor, fixes bump the patch.
2. **Move the changelog's `[Unreleased]` items** into a section for the
   new version in `CHANGELOG.md`, headed `## [X.Y.Z] — YYYY-MM-DD` with
   the date you're actually publishing. Write the entry for anyone
   reading it cold — what changed for them, not which commits landed.
   This section gets pasted into the GitHub Release body verbatim, so a
   leftover placeholder in the heading ships as published release notes.
3. **Merge that to `main`** through the normal PR flow, and let CI go
   green.
4. **Cut a GitHub Release** whose tag is the bare version — `0.2.0`, not
   `v0.2.0`, matching the `0.1.0` convention (a `v` prefix is tolerated by
   the workflow, but don't start a second convention). Target `main`.
   Paste that version's changelog section in as the release body.
5. That's it. Publishing the release triggers
   `.github/workflows/release.yml`, which does the rest.

## What the workflow checks before it uploads

PyPI never lets a version number be reused, even after a delete — an
upload is permanent. So the publish step runs last, behind three gates:

- **`verify`** — the release tag must match `pyproject.toml`'s version.
  Catches the easy mistake of tagging `0.3.0` while pyproject still says
  `0.2.0`, which would otherwise either collide with the published
  `0.2.0` or ship an artifact whose version matches nothing.
- **`test`** — the suite runs against the released commit. "CI was green
  on `main`" is a different claim: a release can be cut from any commit.
- **`build`** — installs the built *wheel* into a clean venv and asks
  each subcommand for its `--help`. This is the direct guard on #103's
  failure: the published `0.1.0` wheel was missing twelve commands the
  docs advertised. A packaging regression fails here instead of after
  someone installs it.

Only if all three pass does `publish` upload to PyPI.

## Prerequisites (already configured)

Publishing uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
via OIDC — no API token is stored as a repository secret. This is already
set up and working: the `0.1.0` GitHub Release published to PyPI fourteen
minutes after it was cut. It needs, on the PyPI side, a trusted publisher
for `dhk/work-ledger` pointing at workflow `release.yml` and environment
`pypi`; and on the GitHub side, an environment named `pypi`.

Nothing here needs re-doing per release. If a publish ever fails with an
OIDC or permissions error, that configuration is where to look first.

## After publishing

Check what PyPI actually serves:

```sh
curl -s https://pypi.org/pypi/work-ledger/json \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['info']['version'])"
```

The JSON API rather than an installer subcommand, deliberately: `pip index
versions` warns that it's experimental and may be removed without notice,
and `uv` has no equivalent at all — `uv pip index` doesn't exist, and a
deliberately-unsatisfiable pin (`uv pip install "work-ledger==99.99.99"`)
reports only that nothing matched, without listing what's available. The
API answers the same question for anyone regardless of installer.

Then install it somewhere clean and run `work-ledger about` — it reports
the version actually installed, which is the number a user would get.

## The drift alarm

`.github/workflows/release-drift.yml` runs weekly and fails when `main`
is more than `MAX_COMMITS_BEHIND` (30) commits past the last release tag.
It is **not** a pull-request check: release drift is a property of time,
not of any one PR, and blocking an unrelated bugfix because a release is
overdue would be the wrong trade. A failing scheduled run surfaces in the
Actions tab and emails the owner — enough to break the silence that let
#103 sit for a month.

A quiet month with no release is fine, and the threshold isn't a schedule.
It's the point past which "is the published package still the tool the
README describes?" deserves an actual answer. If the answer is
legitimately yes and the gap is intended, raise the threshold on purpose
rather than muting the workflow.
