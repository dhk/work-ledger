#!/usr/bin/env bash
# work-ledger quick install.
#
# This script is meant to be read before you run it - that's a reasonable
# instinct for any curl | bash one-liner, this one included. It does exactly
# three things: pip-installs work-ledger from PyPI, prints how to run it,
# and tells you what else to set up for the one optional feature (chapters)
# that calls the Anthropic API directly.
#
# For a more explicit, step-by-step path, see INSTALL.md instead.

set -euo pipefail

PACKAGE="work-ledger"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "error: pip not found for python3. Install pip for your python3 first." >&2
  exit 1
fi

# --user fails outright inside an active virtualenv (venvs disable user
# site-packages by default) - install into the venv itself there instead.
PIP_INSTALL_FLAGS="--user"
if [ -n "${VIRTUAL_ENV:-}" ]; then
  PIP_INSTALL_FLAGS=""
fi

echo "Installing ${PACKAGE} from PyPI..."
python3 -m pip install ${PIP_INSTALL_FLAGS} "${PACKAGE}"

echo
echo "Installed. Try it:"
echo "  work-ledger --once"
echo "  work-ledger limits --once   - rolling-window token tracking, no credentials needed"
echo
echo "work-ledger chapters calls the Anthropic API directly (separate from"
echo "your Claude Code session) to group prompts into initiatives via Haiku,"
echo "and needs its own credentials. Set ANTHROPIC_API_KEY, or run"
echo "'ant auth login' if you have the Anthropic CLI, before using it."
echo
echo "For the visual PNG report (chapters --report --format png), also run:"
echo "  python3 -m pip install ${PIP_INSTALL_FLAGS} \"work-ledger[report]\""
echo "  playwright install chromium"
echo
echo "Full guide, troubleshooting, and an editable-install path: INSTALL.md"
echo "https://github.com/dhk/work-ledger/blob/main/INSTALL.md"
