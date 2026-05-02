#!/bin/bash
# Helper that runs the backfill with the local venv on PATH.
# Used for local dev only; routines invoke the python module directly.
set -e
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$HERE/.venv/lib/python3.13/site-packages:$HERE/src:$PYTHONPATH"
python3 "$HERE/scripts/research/backfill_history.py"
