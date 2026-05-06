#!/usr/bin/env bash
# MT5 Test Bot — Linux/WSL launcher.
#
# Default: paper mode. Subcommand-уудаа дамжуулна:
#   ./start.sh           # paper mode
#   ./start.sh live --symbol EURUSD
#   ./start.sh test
#   ./start.sh preflight

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not in PATH" >&2
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "First run — creating venv and installing dependencies..."
    python3 run.py setup
fi

if [ "$#" -eq 0 ]; then
    exec .venv/bin/python run.py paper
else
    exec .venv/bin/python run.py "$@"
fi
