# Contributing

Contributions should preserve work-ledger's individual-user scope, local-first core, honest Show/Tell/Do maturity, and the architecture in [`docs/architecture.md`](docs/architecture.md).

## Setup

```sh
git clone https://github.com/dhk/work-ledger.git
cd work-ledger
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

The optional JavaScript pattern backend has its own dependencies:

```sh
cd backend
npm ci
```

## Make a focused change

Open an issue or explain the user-visible problem in the pull request. Keep product features, documentation, backend changes, and visual redesigns separate unless they are inseparable. If the change alters a core abstraction, persisted store, or network path, update `docs/architecture.md` in the same pull request.

For pattern-library entries, also follow [CONTRIBUTING-patterns.md](CONTRIBUTING-patterns.md).

## Validate

Run the checks relevant to the files you changed:

```sh
pytest                         # Python behavior
python -m work_ledger.cli --help
python -m work_ledger.cli --once
cd backend && npm test         # backend JavaScript
```

Commands that need real transcripts, credentials, browsers, or deployed services should be tested only when you control those inputs. Otherwise verify their help, parsing, and failure/fallback paths. For documentation, check relative links, shell snippets, command names, privacy claims, and install steps against the current code.

Before opening a pull request, run the full Python and backend suites from a clean checkout or environment. In the pull request, summarize the change, user impact, and exact validation performed.
