#!/bin/bash
# Unload the energy-ping agent and remove the CLI symlink. Leaves data intact.
set -euo pipefail

DEST="${HOME}/energy-log"
PLIST_ID="com.lorenzo.energyping"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_ID}.plist"

echo "Uninstalling energy-ping agent (data in ${DEST} kept)…"

if [[ -f "$PLIST_PATH" ]]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "Removed ${PLIST_PATH}"
else
  echo "No plist at ${PLIST_PATH}"
fi

for candidate in "${HOME}/.local/bin/energy" "/usr/local/bin/energy"; do
  if [[ -L "$candidate" ]]; then
    target="$(readlink "$candidate" || true)"
    if [[ "$target" == "${DEST}/energy" || "$target" == *"energy-log/energy" ]]; then
      rm -f "$candidate"
      echo "Removed symlink ${candidate}"
    fi
  fi
done

echo "Done. CSV/config/state left in ${DEST}."
