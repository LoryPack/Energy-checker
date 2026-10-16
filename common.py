#!/usr/bin/env python3
"""Shared helpers for the energy-ping tool (config, CSV, parsing, time)."""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Tuple

HOME = Path.home()
ROOT = HOME / "energy-log"
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
CSV_PATH = ROOT / "energy.csv"
LOG_DIR = ROOT / "logs"

CSV_HEADER = ["timestamp", "score", "word", "source", "status", "prompted_at"]

DEFAULT_CONFIG: dict[str, Any] = {
    "min_interval_minutes": 45,
    "max_interval_minutes": 75,
    "working_days": [0, 1, 2, 3, 4],  # Mon=0 … Sun=6
    "work_start": "08:30",
    "work_end": "18:30",
    "idle_threshold_seconds": 300,
    "log_skips": True,
    "skip_push_minutes": 10,
    "dialog_timeout_seconds": 90,
}


def load_config() -> dict[str, Any]:
    """Merge on-disk config with defaults. Missing file → defaults only."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.is_file():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def write_default_config() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
            f.write("\n")


def load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            with STATE_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_state(state: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE_PATH)


def now_local() -> datetime:
    return datetime.now().astimezone()


def isoformat(dt: datetime) -> str:
    """ISO 8601 with local UTC offset, seconds precision."""
    return dt.astimezone().replace(microsecond=0).isoformat()


def parse_hhmm(s: str) -> Tuple[int, int]:
    parts = s.strip().split(":")
    return int(parts[0]), int(parts[1])


def within_working_hours(dt: datetime, cfg: dict[str, Any]) -> bool:
    if dt.weekday() not in cfg["working_days"]:
        return False
    sh, sm = parse_hhmm(cfg["work_start"])
    eh, em = parse_hhmm(cfg["work_end"])
    start = dt.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= dt < end


SCORE_RE = re.compile(
    r"^\s*([1-5])(?:\s+(.+?))?\s*$",
    re.UNICODE,
)

# Emoji labels used in the ping dialog (score → display).
ENERGY_CHOICES: list[tuple[int, str]] = [
    (1, "😴"),
    (2, "😕"),
    (3, "😐"),
    (4, "🙂"),
    (5, "⚡️"),
]


def parse_energy_input(text: str) -> Optional[Tuple[int, str]]:
    """
    Parse '<int 1-5> [optional word(s)]'.
    Returns (score, word) or None if invalid.
    """
    if text is None:
        return None
    m = SCORE_RE.match(text.strip())
    if not m:
        return None
    score = int(m.group(1))
    word = (m.group(2) or "").strip()
    return score, word


def append_csv_row(row: dict[str, str]) -> None:
    """Append one row atomically (append + flush + fsync). Never rewrite."""
    ROOT.mkdir(parents=True, exist_ok=True)
    write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
    with CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in CSV_HEADER})
        f.flush()
        os.fsync(f.fileno())


def random_interval_delta(cfg: dict[str, Any]) -> timedelta:
    import random

    lo = int(cfg["min_interval_minutes"])
    hi = int(cfg["max_interval_minutes"])
    if hi < lo:
        lo, hi = hi, lo
    minutes = random.randint(lo, hi)
    return timedelta(minutes=minutes)


def push_next_ping(cfg: dict[str, Any], minutes: Optional[float] = None) -> datetime:
    """Set next_ping_at to now + minutes (or random interval) and persist."""
    if minutes is None:
        delta = random_interval_delta(cfg)
    else:
        delta = timedelta(minutes=minutes)
    nxt = now_local() + delta
    state = load_state()
    state["next_ping_at"] = isoformat(nxt)
    save_state(state)
    return nxt
