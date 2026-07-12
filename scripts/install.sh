#!/usr/bin/env bash
# work-ledger quick install.
#
# This script is meant to be read before you run it - that's a reasonable
# instinct for any curl | bash one-liner, this one included. It does exactly
# three things: pip-installs work-ledger from this repo, prints how to run
# it, and tells you what else to set up for the two optional features
# (chapters, limits) that call the Anthropic API directly.
#
# For a more explicit, step-by-step path, see INSTALL.md instead.

set -euo pipefail

REPO_URL="git+https://github.com/dhk/work-ledger.git"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi

if ! command -v pip3 >/dev/null 2>&1 && ! python3 -m pip --version >/dev/null 2>&1; then
  echo "error: pip not found. Install pip for your python3 first." >&2
  exit 1
fi

echo "Installing work-ledger from ${REPO_URL}..."
python3 -m pip install --user "${REPO_URL}"

echo
echo "Installed. Try it:"
echo "  work-ledger --once"
echo
echo "Two features call the Anthropic API directly (separate from your"
echo "Claude Code session) and need credentials of their own:"
echo "  work-ledger chapters   - groups prompts into initiatives via Haiku"
echo "  work-ledger limits     - rolling-window token tracking"
echo "Set ANTHROPIC_API_KEY, or run 'ant auth login' if you have the"
echo "Anthropic CLI, before using either."
echo
echo "For the visual PNG report (chapters --report --format png), also run:"
echo "  python3 -m pip install --user \"work-ledger[report]\""
echo "  playwright install chromium"
echo
echo "Full guide, troubleshooting, and an editable-install path: INSTALL.md"
echo "https://github.com/dhk/work-ledger/blob/main/INSTALL.md"
