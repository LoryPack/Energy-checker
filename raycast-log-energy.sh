#!/bin/bash
# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Log Energy
# @raycast.mode silent
# @raycast.packageName Energy Log
#
# Optional parameters:
# @raycast.icon ⚡️
# @raycast.argument1 { "type": "text", "placeholder": "Score 1–5" }
# @raycast.argument2 { "type": "text", "placeholder": "Word (optional)", "optional": true }
#
# Documentation:
# @raycast.description Append an energy score to ~/energy-log/energy.csv
# @raycast.author Lorenzo

set -euo pipefail

ENERGY_BIN="${HOME}/energy-log/energy"
if [[ ! -x "$ENERGY_BIN" ]]; then
  ENERGY_BIN="$(dirname "$0")/energy"
fi

SCORE="${1:-}"
WORD="${2:-}"

if [[ -z "$SCORE" ]]; then
  echo "Score required (1–5)" >&2
  exit 1
fi

if [[ -n "$WORD" ]]; then
  exec "$ENERGY_BIN" "$SCORE" "$WORD"
else
  exec "$ENERGY_BIN" "$SCORE"
fi
