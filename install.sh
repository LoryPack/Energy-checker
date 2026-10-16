#!/bin/bash
# Install energy-ping into ~/energy-log and load the launchd agent.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${HOME}/energy-log"
PLIST_ID="com.lorenzo.energyping"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_ID}.plist"
LABEL="$PLIST_ID"

# Prefer a writable user bin; fall back to /usr/local/bin if present/writable.
if [[ -d "${HOME}/.local/bin" ]] || mkdir -p "${HOME}/.local/bin" 2>/dev/null; then
  BIN_DIR="${HOME}/.local/bin"
elif [[ -w "/usr/local/bin" ]]; then
  BIN_DIR="/usr/local/bin"
else
  mkdir -p "${HOME}/.local/bin"
  BIN_DIR="${HOME}/.local/bin"
fi

echo "Installing energy-ping → ${DEST}"

mkdir -p "${DEST}/logs"
mkdir -p "$(dirname "$PLIST_PATH")"

# Copy scripts (keep data/config if already present)
for f in common.py ping.py energy raycast-log-energy.sh uninstall.sh README.md; do
  if [[ -f "${SRC}/${f}" ]]; then
    cp "${SRC}/${f}" "${DEST}/${f}"
  fi
done
# Keep a copy of install.sh too
cp "${SRC}/install.sh" "${DEST}/install.sh"

chmod +x "${DEST}/ping.py" "${DEST}/energy" "${DEST}/raycast-log-energy.sh" \
  "${DEST}/install.sh" "${DEST}/uninstall.sh"

# Default config (do not overwrite existing)
if [[ ! -f "${DEST}/config.json" ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / "energy-log" / "config.json"
cfg = {
    "min_interval_minutes": 45,
    "max_interval_minutes": 75,
    "working_days": [0, 1, 2, 3, 4],
    "work_start": "08:30",
    "work_end": "18:30",
    "idle_threshold_seconds": 300,
    "log_skips": True,
    "skip_push_minutes": 10,
    "dialog_timeout_seconds": 90,
}
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {p}")
PY
else
  echo "Keeping existing config.json"
fi

# Resolve python3 absolute path for the plist
PYTHON3="$(command -v python3)"
PING_PY="${DEST}/ping.py"
STDOUT_LOG="${DEST}/logs/stdout.log"
STDERR_LOG="${DEST}/logs/stderr.log"

# Unload previous agent if loaded
if launchctl list "$LABEL" &>/dev/null; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON3}</string>
    <string>${PING_PY}</string>
  </array>
  <key>StartInterval</key>
  <integer>300</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${STDOUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${STDERR_LOG}</string>
  <key>WorkingDirectory</key>
  <string>${DEST}</string>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH"

# Symlink CLI
ln -sf "${DEST}/energy" "${BIN_DIR}/energy"

echo ""
echo "Installed."
echo "  Data / config : ${DEST}"
echo "  Agent plist   : ${PLIST_PATH}"
echo "  CLI           : ${BIN_DIR}/energy"
echo ""
echo "Quick test:"
echo "  python3 ${DEST}/ping.py --dry-check"
echo "  python3 ${DEST}/ping.py --force          # shows dialog"
echo "  energy 3 focused                         # manual log"
echo "  tail -f ${DEST}/energy.csv"
echo ""
echo "Pause:   launchctl unload ${PLIST_PATH}"
echo "Resume:  launchctl load ${PLIST_PATH}"
echo "Remove:  ${DEST}/uninstall.sh"
