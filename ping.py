#!/usr/bin/env python3
"""
Energy ping — launchd-driven prompt to rate energy 1–5 via emoji buttons.

Designed to run every ~5 minutes via launchd; scheduling state lives in state.json.
Use --force to show the dialog immediately (testing).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# Allow running from ~/energy-log or a source checkout
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    ENERGY_CHOICES,
    ROOT,
    append_csv_row,
    isoformat,
    load_config,
    load_state,
    now_local,
    parse_energy_input,
    push_next_ping,
    save_state,
    within_working_hours,
)


def hid_idle_seconds() -> Optional[float]:
    """Read HIDIdleTime from IOHIDSystem (nanoseconds → seconds)."""
    try:
        out = subprocess.check_output(
            ["ioreg", "-c", "IOHIDSystem"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        if "HIDIdleTime" in line:
            # e.g. '"HIDIdleTime" = 123456789'
            parts = line.split("=")
            if len(parts) >= 2:
                raw = parts[-1].strip().rstrip(";")
                try:
                    return int(raw) / 1_000_000_000.0
                except ValueError:
                    return None
    return None


def is_screen_locked() -> bool:
    """
    True if the console session reports the screen locked.

    Reads CGSessionCopyCurrentDictionary via ctypes, serializes it to a plist,
    and checks CGSSessionScreenIsLocked. No pip deps. Fails open (False).
    """
    try:
        import ctypes
        import ctypes.util
        import plistlib

        cg_path = ctypes.util.find_library("CoreGraphics")
        cf_path = ctypes.util.find_library("CoreFoundation")
        if not cg_path or not cf_path:
            return False

        cg = ctypes.CDLL(cg_path)
        cf = ctypes.CDLL(cf_path)

        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        session = cg.CGSessionCopyCurrentDictionary()
        if not session:
            return False

        # CFPropertyListCreateData → XML bytes (avoids fragile CFBoolean/CFRelease paths)
        kCFPropertyListXMLFormat_v1_0 = 100
        cf.CFPropertyListCreateData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        cf.CFPropertyListCreateData.restype = ctypes.c_void_p
        data_ref = cf.CFPropertyListCreateData(
            None, session, kCFPropertyListXMLFormat_v1_0, 0, None
        )

        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None
        cf.CFRelease(session)

        if not data_ref:
            return False

        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
        cf.CFDataGetLength.restype = ctypes.c_long
        ptr = cf.CFDataGetBytePtr(data_ref)
        length = cf.CFDataGetLength(data_ref)
        raw = ctypes.string_at(ptr, length)
        cf.CFRelease(data_ref)

        info = plistlib.loads(raw)
        return bool(info.get("CGSSessionScreenIsLocked", False))
    except Exception:
        return False


def should_skip_quietly(cfg: dict) -> Optional[str]:
    """
    Return a reason string if we should skip the prompt, else None.
    Caller pushes next_ping_at forward ~10 min on skip.
    """
    now = now_local()
    if not within_working_hours(now, cfg):
        return "outside_hours"

    if is_screen_locked():
        return "screen_locked"

    idle = hid_idle_seconds()
    if idle is not None and idle > float(cfg["idle_threshold_seconds"]):
        return "idle"

    return None


def show_energy_dialog(timeout: int) -> Tuple[str, Optional[int], str]:
    """
    Native emoji-button alert via JXA / NSAlert (osascript), with optional
    word text field as accessory view.

    Returns (outcome, score, word) where outcome is 'ok' | 'skip' | 'timeout'.
    """
    # Button titles: "😴 1", …, "⚡️ 5", then Skip.
    # NSAlertFirstButtonReturn = 1000, then 1001, …
    titles = [f"{emoji} {score}" for score, emoji in ENERGY_CHOICES] + ["Skip"]
    titles_js = ", ".join(f'"{t}"' for t in titles)

    # JXA NSAlert — must activate NSApp or the modal runs invisibly (hangs).
    # AppleScript `display dialog` is capped at 3 buttons, so JXA is required.
    # Wire format: OK|<score>|<word>  (word may be empty; no newlines)
    script = f"""
ObjC.import("Cocoa");
function run() {{
  var app = $.NSApplication.sharedApplication;
  app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
  app.activateIgnoringOtherApps(true);

  var alert = $.NSAlert.alloc.init;
  alert.setMessageText("Energy");
  alert.setInformativeText("How’s your energy?  (1–5 · Esc skips)");
  var titles = [{titles_js}];
  var buttons = [];
  for (var i = 0; i < titles.length; i++) {{
    buttons.push(alert.addButtonWithTitle(titles[i]));
  }}
  // Digit keys → scores; Escape → Skip. These only fire when a text field
  // is NOT first responder — so wrap the field in a plain NSView so NSAlert
  // does not auto-focus it. Click the field only when adding a word.
  for (var s = 0; s < 5; s++) {{
    buttons[s].keyEquivalent = String(s + 1);
  }}
  buttons[5].keyEquivalent = String.fromCharCode(27);  // Escape

  var field = $.NSTextField.alloc.initWithFrame($.NSMakeRect(0, 0, 280, 24));
  field.setPlaceholderString("optional word (click to type)");
  var box = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, 280, 24));
  box.addSubview(field);
  alert.setAccessoryView(box);

  var resp = alert.runModal;
  var idx = resp - 1000;
  if (idx < 0 || idx >= titles.length || titles[idx] === "Skip") {{
    return "SKIP|";
  }}
  var m = titles[idx].match(/(\\d)\\s*$/);
  if (!m) return "SKIP|";
  var word = ObjC.unwrap(field.stringValue) || "";
  word = String(word).replace(/[\\r\\n|]/g, " ").trim();
  return "OK|" + m[1] + "|" + word;
}}
"""
    try:
        proc = subprocess.Popen(
            ["osascript", "-l", "JavaScript", "-e", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            out, err = proc.communicate(timeout=int(timeout))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return "timeout", None, ""
    except OSError:
        return "skip", None, ""

    line = (out or "").strip()
    if not line:
        return _show_energy_chooser(timeout)

    if line.startswith("TIMEOUT|"):
        return "timeout", None, ""
    if line.startswith("SKIP|"):
        return "skip", None, ""
    if line.startswith("OK|"):
        parts = line.split("|", 2)
        if len(parts) >= 2:
            try:
                score = int(parts[1])
            except ValueError:
                return "skip", None, ""
            word = parts[2].strip() if len(parts) > 2 else ""
            if 1 <= score <= 5:
                return "ok", score, word
    return "skip", None, ""


def _show_energy_chooser(timeout: int) -> Tuple[str, Optional[int], str]:
    """Fallback emoji list if NSAlert fails (no accessory field → empty word)."""
    items = ", ".join(f'"{emoji}  {score}"' for score, emoji in ENERGY_CHOICES)
    script = f'''
try
  with timeout of {int(timeout)} seconds
    set energyChoices to {{{items}}}
    set selected to choose from list energyChoices ¬
      with title "Energy" ¬
      with prompt "How’s your energy right now?" ¬
      default items {{"😐  3"}} ¬
      OK button name "Log" ¬
      cancel button name "Skip"
    if selected is false then return "SKIP|"
    return "OK|" & (item 1 of selected) & "|"
  end timeout
on error number -1712
  return "TIMEOUT|"
on error number -128
  return "SKIP|"
end try
'''
    try:
        out = subprocess.check_output(
            ["osascript", "-e", script],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=int(timeout) + 5,
        ).strip()
    except subprocess.TimeoutExpired:
        return "timeout", None, ""
    except (OSError, subprocess.CalledProcessError):
        return "skip", None, ""

    if out.startswith("TIMEOUT|"):
        return "timeout", None, ""
    if out.startswith("SKIP|"):
        return "skip", None, ""
    if out.startswith("OK|"):
        parts = out.split("|", 2)
        tail = parts[1].strip() if len(parts) > 1 else ""
        for score, emoji in ENERGY_CHOICES:
            if tail.endswith(str(score)) or tail.startswith(emoji):
                return "ok", score, ""
    return "skip", None, ""


def prompt_and_log(cfg: dict) -> None:
    prompted_at = now_local()
    prompted_s = isoformat(prompted_at)
    timeout = int(cfg.get("dialog_timeout_seconds", 90))

    outcome, score, word = show_energy_dialog(timeout)
    if outcome == "ok" and score is not None:
        append_csv_row(
            {
                "timestamp": isoformat(now_local()),
                "score": str(score),
                "word": word,
                "source": "ping",
                "status": "logged",
                "prompted_at": prompted_s,
            }
        )
        push_next_ping(cfg)
        return

    status = "timeout" if outcome == "timeout" else "skipped"
    if cfg.get("log_skips", True):
        append_csv_row(
            {
                "timestamp": isoformat(now_local()),
                "score": "",
                "word": "",
                "source": "ping",
                "status": status,
                "prompted_at": prompted_s,
            }
        )
    push_next_ping(cfg)


def ensure_next_ping(cfg: dict) -> datetime:
    """Load or initialize next_ping_at."""
    state = load_state()
    raw = state.get("next_ping_at")
    if raw:
        try:
            # fromisoformat handles +01:00 offsets
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return push_next_ping(cfg)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Energy ping (launchd entrypoint)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Show the prompt immediately (ignore schedule / skip checks)",
    )
    parser.add_argument(
        "--dry-check",
        action="store_true",
        help="Print schedule/skip status and exit (no dialog)",
    )
    args = parser.parse_args(argv)

    ROOT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    if args.force:
        if args.dry_check:
            print("force: would prompt now")
            return 0
        prompt_and_log(cfg)
        return 0

    next_at = ensure_next_ping(cfg)
    now = now_local()

    if args.dry_check:
        reason = should_skip_quietly(cfg)
        print(f"now={isoformat(now)}")
        print(f"next_ping_at={isoformat(next_at)}")
        print(f"due={now >= next_at}")
        print(f"skip_reason={reason or 'none'}")
        print(f"idle_seconds={hid_idle_seconds()}")
        print(f"screen_locked={is_screen_locked()}")
        print(f"within_hours={within_working_hours(now, cfg)}")
        return 0

    if now < next_at:
        return 0

    reason = should_skip_quietly(cfg)
    if reason:
        push_next_ping(cfg, minutes=float(cfg.get("skip_push_minutes", 10)))
        return 0

    prompt_and_log(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
