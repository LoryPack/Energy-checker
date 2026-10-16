# Energy ping

Tiny, zero-dependency macOS tool that randomly asks you to rate your energy (1–5, emoji buttons) while you’re at the computer, and appends rows to a CSV you can later join with Google Calendar / Reclaim by timestamp.

Uses only built-ins: Python 3, `osascript`, `launchd`, `ioreg`.

## Install

```bash
cd /path/to/this/repo   # or wherever these scripts live
chmod +x install.sh
./install.sh
```

This will:

- Copy scripts into `~/energy-log/`
- Write `~/energy-log/config.json` if missing
- Load `~/Library/LaunchAgents/com.lorenzo.energyping.plist` (runs every 5 minutes)
- Symlink `energy` into `~/.local/bin` (or `/usr/local/bin`)

Ensure `~/.local/bin` is on your `PATH` if that’s where the symlink landed.

### Raycast

Copy or symlink `~/energy-log/raycast-log-energy.sh` into your Raycast Script Commands folder. It exposes **score** (required) and **word** (optional).

## Where data lives

| Path | Purpose |
|------|---------|
| `~/energy-log/energy.csv` | Append-only log |
| `~/energy-log/config.json` | Schedule / thresholds |
| `~/energy-log/state.json` | `next_ping_at` |
| `~/energy-log/logs/` | launchd stdout/stderr |

CSV columns: `timestamp,score,word,source,status,prompted_at`

- `timestamp` — ISO 8601 with local offset when you answered (or skipped)
- `source` — `ping` or `manual`
- `status` — `logged` | `skipped` | `timeout`
- `prompted_at` — when the dialog appeared (empty for manual)

## Behaviour

1. launchd runs `ping.py` every 5 minutes (`StartInterval=300`, `RunAtLoad=true`).
2. Script reads `next_ping_at` from `state.json`. If now is earlier, it exits.
3. When due, it skips (and pushes `next_ping_at` ~10 minutes) if you’re idle > 5 min, the screen is locked, or you’re outside working hours.
4. Otherwise it shows a native alert with emoji buttons **😴1 · 😕2 · 😐3 · 🙂4 · ⚡️5** (+ Skip), an optional word text field below, and a 90s timeout.
5. After any prompt attempt, a new random `next_ping_at` is set ~45–75 minutes ahead (uniform).

## Manual logging

```bash
energy 3
energy 2 foggy
```

## Change schedule / hours

Edit `~/energy-log/config.json`:

```json
{
  "min_interval_minutes": 45,
  "max_interval_minutes": 75,
  "working_days": [0, 1, 2, 3, 4],
  "work_start": "08:30",
  "work_end": "18:30",
  "idle_threshold_seconds": 300,
  "log_skips": true,
  "skip_push_minutes": 10,
  "dialog_timeout_seconds": 90
}
```

`working_days`: Monday = 0 … Sunday = 6. No need to reload launchd after config edits — the next run picks them up.

## Pause / resume / uninstall

```bash
# Pause
launchctl unload ~/Library/LaunchAgents/com.lorenzo.energyping.plist

# Resume
launchctl load ~/Library/LaunchAgents/com.lorenzo.energyping.plist

# Uninstall agent + CLI symlink (keeps CSV/config/state)
~/energy-log/uninstall.sh
```

## Manual test checklist

```bash
# 1) Schedule / skip diagnostics (no GUI)
python3 ~/energy-log/ping.py --dry-check

# 2) Force the dialog (GUI)
python3 ~/energy-log/ping.py --force
# Click an emoji (1–5) → row status=logged
# Click Skip → status=skipped (if log_skips)
# Wait 90s → status=timeout

# 3) Manual CLI
energy 4 calm
tail -n 3 ~/energy-log/energy.csv

# 4) Confirm agent is loaded
launchctl list | grep energyping

# 5) Invalid parse path (unit-style, no GUI)
python3 - <<'PY'
import sys; sys.path.insert(0, str(__import__("pathlib").Path.home()/"energy-log"))
from common import parse_energy_input
assert parse_energy_input("3 scattered") == (3, "scattered")
assert parse_energy_input("6") is None
assert parse_energy_input("10") is None
print("parse ok")
PY
```

## Joining with calendar

Both sides have timestamps. Parse `timestamp` as timezone-aware datetimes and interval-join to Reclaim/Google Calendar events (e.g. “which event contains this ping?”). Skipped/timeout rows are optional noise — filter `status == logged` if you only want answers.
