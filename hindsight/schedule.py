from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

LABEL = "io.github.enkoic.hindsight"


# ───────── shared ─────────


def _hindsight_bin() -> str:
    """Best-effort absolute path to the hindsight CLI."""
    found = shutil.which("hindsight")
    if found:
        return found
    return f"{shutil.which('python3') or '/usr/bin/python3'} -m hindsight"


def _is_darwin() -> bool:
    return os.uname().sysname == "Darwin"


def _is_linux() -> bool:
    return os.uname().sysname == "Linux"


@dataclass(frozen=True)
class InstalledSchedule:
    platform: str  # "darwin" | "linux"
    primary: Path  # plist (macOS) or .timer (linux)
    extras: list[Path]  # additional files (e.g. .service for linux)


# ───────── macOS launchd ─────────


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


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
    if not _is_darwin():
        raise RuntimeError("macOS scheduler invoked on non-Darwin platform")
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_plist_xml(hour, minute, targets), encoding="utf-8")
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


# ───────── Linux systemd (--user) ─────────


def systemd_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def systemd_service_path() -> Path:
    return systemd_unit_dir() / "hindsight.service"


def systemd_timer_path() -> Path:
    return systemd_unit_dir() / "hindsight.timer"


def _service_unit(targets: str) -> str:
    bin_path = _hindsight_bin()
    return f"""[Unit]
Description=Hindsight — daily activity digest
Documentation=https://github.com/Enkoic/hindsight

[Service]
Type=oneshot
ExecStart={bin_path} run --day yesterday --targets {targets}
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
WorkingDirectory=%h
StandardOutput=append:%h/.local/state/hindsight/hindsight.log
StandardError=append:%h/.local/state/hindsight/hindsight.err

[Install]
WantedBy=default.target
"""


def _timer_unit(hour: int, minute: int) -> str:
    return f"""[Unit]
Description=Run hindsight daily at {hour:02d}:{minute:02d}

[Timer]
OnCalendar=*-*-* {hour:02d}:{minute:02d}:00
Persistent=true
Unit=hindsight.service

[Install]
WantedBy=timers.target
"""


def linux_install(hour: int = 23, minute: int = 0, targets: str = "markdown") -> Path:
    if not _is_linux():
        raise RuntimeError("systemd scheduler invoked on non-Linux platform")
    if not shutil.which("systemctl"):
        raise RuntimeError("systemctl not found — install systemd or use cron manually")

    unit_dir = systemd_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / ".local" / "state" / "hindsight"
    log_dir.mkdir(parents=True, exist_ok=True)

    systemd_service_path().write_text(_service_unit(targets), encoding="utf-8")
    systemd_timer_path().write_text(_timer_unit(hour, minute), encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", "hindsight.timer"], check=False
    )
    return systemd_timer_path()


def linux_uninstall() -> Path | None:
    timer = systemd_timer_path()
    service = systemd_service_path()
    if not timer.exists() and not service.exists():
        return None
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "hindsight.timer"], check=False
    )
    timer.unlink(missing_ok=True)
    service.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return timer


# ───────── platform-aware façade ─────────


def install(hour: int = 23, minute: int = 0, targets: str = "markdown") -> InstalledSchedule:
    if _is_darwin():
        p = macos_install(hour, minute, targets)
        return InstalledSchedule("darwin", p, [])
    if _is_linux():
        p = linux_install(hour, minute, targets)
        return InstalledSchedule("linux", p, [systemd_service_path()])
    raise RuntimeError(f"unsupported platform: {os.uname().sysname}")


def uninstall() -> InstalledSchedule | None:
    if _is_darwin():
        p = macos_uninstall()
        return InstalledSchedule("darwin", p, []) if p else None
    if _is_linux():
        p = linux_uninstall()
        return InstalledSchedule("linux", p, [systemd_service_path()]) if p else None
    raise RuntimeError(f"unsupported platform: {os.uname().sysname}")


def show_paths() -> list[Path]:
    if _is_darwin():
        return [plist_path()]
    if _is_linux():
        return [systemd_timer_path(), systemd_service_path()]
    return []
