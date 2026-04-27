from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

LABEL = "io.github.enkoic.hindsight"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _hindsight_bin() -> str:
    """Best-effort absolute path to the hindsight CLI."""
    found = shutil.which("hindsight")
    if found:
        return found
    # Fall back to the python module form so it still works without an entry script on PATH.
    return f"{shutil.which('python3') or '/usr/bin/python3'} -m hindsight"


def _plist_xml(hour: int, minute: int, targets: str) -> str:
    log_dir = Path.home() / "Library" / "Logs" / "hindsight"
    log_dir.mkdir(parents=True, exist_ok=True)
    bin_path = _hindsight_bin()
    program_args = bin_path.split() + ["run", "--day", "yesterday", "--targets", targets]
    args_xml = "\n        ".join(f"<string>{a}</string>" for a in program_args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        {args_xml}
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>{Path.home()}</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/hindsight.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/hindsight.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""


def macos_install(hour: int = 23, minute: int = 0, targets: str = "markdown") -> Path:
    if os.uname().sysname != "Darwin":
        raise RuntimeError("schedule install currently supports macOS launchd only")
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_plist_xml(hour, minute, targets), encoding="utf-8")
    # Try modern bootstrap first, fall back to legacy load.
    uid = os.getuid()
    domain = f"gui/{uid}"
    subprocess.run(["launchctl", "bootout", domain, str(p)], capture_output=True)
    res = subprocess.run(
        ["launchctl", "bootstrap", domain, str(p)], capture_output=True, text=True
    )
    if res.returncode != 0:
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        subprocess.run(["launchctl", "load", str(p)], capture_output=True, check=False)
    return p


def macos_uninstall() -> Path | None:
    p = plist_path()
    if not p.exists():
        return None
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    p.unlink(missing_ok=True)
    return p
