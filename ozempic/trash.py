"""
Side effects for ozempic uninstall: Finder Trash, launchd unload, app quit.
Never deletes permanently. No external dependencies — stdlib only.
"""

from __future__ import annotations

import getpass
import os
import plistlib
import re
import subprocess
import time
from pathlib import Path

from ozempic.uninstaller import AppInfo

# Bundle IDs and launchd labels that are safe to put inside a script string.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

_TRASH_SCRIPT = [
    "on run argv",
    "set fs to {}",
    "repeat with p in argv",
    "set end of fs to (POSIX file (p as text)) as alias",
    "end repeat",
    'tell application "Finder" to delete fs',
    "end run",
]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def finder_available() -> bool:
    """True if this terminal may automate Finder (triggers the Automation prompt once)."""
    r = _run(["osascript", "-e", 'tell application "Finder" to get name of startup disk'])
    return r.returncode == 0


def hosts_terminal(info: AppInfo) -> bool:
    """True if ozempic is running inside the app being uninstalled."""
    host = os.environ.get("__CFBundleIdentifier", "").lower()
    return bool(host) and host in {i.lower() for i in (info.bundle_id, *info.helper_ids)}


def is_running(info: AppInfo) -> bool:
    return _run(["pgrep", "-f", f"{info.path}/Contents/"]).returncode == 0


def quit_app(info: AppInfo, timeout: float = 10.0) -> bool:
    """Ask the app to quit; True once nothing from its bundle is running."""
    if not _SAFE_ID.match(info.bundle_id):
        return False
    _run(["osascript", "-e", f'quit app id "{info.bundle_id}"'])
    deadline = time.monotonic() + timeout
    while is_running(info):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)
    return True


def _label(plist: Path) -> str | None:
    try:
        with open(plist, "rb") as f:
            label = plistlib.load(f).get("Label")
    except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
        return None
    return label if isinstance(label, str) and _SAFE_ID.match(label) else None


def unload_launchd(paths: list[Path]) -> None:
    """bootout the launchd jobs defined by *paths* before their plists go to the Trash."""
    home = str(Path.home()) + "/"
    system_labels = []
    for p in paths:
        label = _label(p)
        if not label:
            continue
        if str(p).startswith(home):
            _run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"])
        else:
            system_labels.append(label)
    if system_labels:
        # ponytail: Finder asks for its own admin password for root-owned paths,
        # so a system-daemon uninstall prompts twice; merge only if it annoys.
        cmd = "; ".join(f"launchctl bootout system/{l}" for l in system_labels)
        _run(["osascript", "-e", f'do shell script "{cmd}" with administrator privileges'])


def move_to_trash(paths: list[Path]) -> list[tuple[Path, str]]:
    """Move *paths* to the Trash via Finder (Put Back works). Returns the ones that failed."""
    if not paths:
        return []
    args = ["osascript"]
    for line in _TRASH_SCRIPT:
        args += ["-e", line]
    args += ["--", *map(str, paths)]
    r = _run(args)
    reason = (r.stderr or "").strip() or "still present"
    return [(p, reason) for p in paths if p.exists() or p.is_symlink()]


def flush_prefs() -> None:
    """Restart cfprefsd so trashed preference plists aren't written back from its cache."""
    _run(["killall", "-u", getpass.getuser(), "cfprefsd"])
