"""
Uninstaller module for ozempic: find an app and every file it left around.
No external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import plistlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class UninstallError(Exception):
    """Raised when an app cannot or must not be uninstalled."""


@dataclass
class Roots:
    home: Path
    system_library: Path
    app_dirs: list[Path]
    caskroom: Path

    @classmethod
    def default(cls) -> Roots:
        home = Path.home()
        return cls(
            home=home,
            system_library=Path("/Library"),
            app_dirs=[Path("/Applications"), home / "Applications"],
            caskroom=Path("/opt/homebrew/Caskroom"),
        )


@dataclass
class AppInfo:
    path: Path
    bundle_id: str
    helper_ids: list[str]
    names: list[str]
    vendor: str | None
    team_id: str | None
    cask: str | None
    zap_paths: list[Path] = field(default_factory=list)


# Places inside Contents/ where embedded helper bundles live.
_HELPER_DIRS = (
    "Library/LoginItems",
    "Library/LaunchServices",
    "XPCServices",
    "PlugIns",
    "Frameworks",
    "Helpers",
)


def _read_plist(path: Path) -> dict | None:
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def _bundle_plist(bundle: Path) -> dict | None:
    """Info.plist of a bundle: Contents/Info.plist, or Info.plist for flat bundles."""
    return _read_plist(bundle / "Contents" / "Info.plist") or _read_plist(bundle / "Info.plist")


def _iter_apps(roots: Roots) -> list[Path]:
    apps: list[Path] = []
    for d in roots.app_dirs:
        if not d.is_dir():
            continue
        apps.extend(sorted(d.glob("*.app")))
        apps.extend(sorted(d.glob("*/*.app")))
    return apps


def find_apps(query: str, roots: Roots) -> list[Path]:
    """Find installed apps matching a name, a bundle ID, or a .app path."""
    p = Path(query).expanduser()
    if p.suffix == ".app" and p.is_dir():
        return [p]
    q = query.lower()
    found = []
    for app in _iter_apps(roots):
        if app.stem.lower() == q:
            found.append(app)
            continue
        plist = _bundle_plist(app) or {}
        if str(plist.get("CFBundleIdentifier", "")).lower() == q:
            found.append(app)
    return found


def _helper_ids(app: Path, main_id: str) -> list[str]:
    contents = app / "Contents"
    ids: list[str] = []
    for rel in _HELPER_DIRS:
        d = contents / rel
        if not d.is_dir():
            continue
        try:
            children = sorted(d.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            hid = (_bundle_plist(child) or {}).get("CFBundleIdentifier")
            if isinstance(hid, str) and hid != main_id and hid not in ids:
                ids.append(hid)
    return ids


def _name_keys(app: Path, plist: dict) -> list[str]:
    keys: list[str] = []
    for raw in (plist.get("CFBundleName"), plist.get("CFBundleDisplayName"), app.stem):
        if not isinstance(raw, str) or not raw.strip():
            continue
        for k in (raw.lower(), raw.lower().replace(" ", "")):
            if k not in keys:
                keys.append(k)
    return keys


def _vendor(bundle_id: str) -> str | None:
    parts = bundle_id.lower().split(".")
    if len(parts) < 2 or len(parts[1]) < 4:
        return None
    return parts[1]


def _team_id(app: Path) -> str | None:
    try:
        r = subprocess.run(["codesign", "-dv", "--verbose=2", str(app)],
                           capture_output=True, text=True)
    except OSError:
        return None
    m = re.search(r"TeamIdentifier=(\S+)", r.stderr or "")
    if not m or m.group(1) == "not":
        return None
    return m.group(1)


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _cask_for(app: Path, roots: Roots) -> tuple[str | None, list[Path]]:
    try:
        r = subprocess.run(["brew", "info", "--cask", "--json=v2", "--installed"],
                           capture_output=True, text=True)
    except OSError:
        return None, []
    if r.returncode != 0:
        return None, []
    try:
        casks = json.loads(r.stdout).get("casks", [])
    except (json.JSONDecodeError, AttributeError):
        return None, []

    for cask in casks:
        artifacts = cask.get("artifacts", [])
        app_names: set[str] = set()
        for art in artifacts:
            if not isinstance(art, dict) or "app" not in art:
                continue
            for item in _as_list(art["app"]):
                if isinstance(item, str):
                    app_names.add(Path(item).name)
                elif isinstance(item, dict) and isinstance(item.get("target"), str):
                    app_names.add(Path(item["target"]).name)
            if isinstance(art.get("target"), str):
                app_names.add(Path(art["target"]).name)
        if app.name not in app_names:
            continue

        zap: list[Path] = []
        for art in artifacts:
            if not isinstance(art, dict) or "zap" not in art:
                continue
            for stanza in _as_list(art["zap"]):
                if not isinstance(stanza, dict):
                    continue
                for key in ("trash", "delete"):
                    for pattern in _as_list(stanza.get(key)):
                        if isinstance(pattern, str):
                            zap.extend(_expand(pattern, roots))
        return cask.get("token"), sorted(set(zap))
    return None, []


def _expand(pattern: str, roots: Roots) -> list[Path]:
    if pattern.startswith("~/"):
        pattern = str(roots.home / pattern[2:])
    if not any(c in pattern for c in "*?["):
        p = Path(pattern)
        return [p] if p.exists() or p.is_symlink() else []
    p = Path(pattern)
    anchor = Path(p.anchor)
    return sorted(anchor.glob(str(p.relative_to(anchor))))


def read_app_info(app: Path, roots: Roots) -> AppInfo:
    """Gather every search key for *app*. Raises UninstallError for Apple apps."""
    if str(app).startswith("/System/"):
        raise UninstallError(f"{app.name} is part of macOS and cannot be uninstalled.")
    plist = _read_plist(app / "Contents" / "Info.plist")
    if not plist or not isinstance(plist.get("CFBundleIdentifier"), str):
        raise UninstallError(f"{app} has no readable Info.plist.")
    bundle_id = plist["CFBundleIdentifier"]
    if bundle_id.lower().startswith("com.apple."):
        raise UninstallError(f"{app.name} ({bundle_id}) is Apple software; refusing.")
    cask, zap = _cask_for(app, roots)
    return AppInfo(
        path=app,
        bundle_id=bundle_id,
        helper_ids=_helper_ids(app, bundle_id),
        names=_name_keys(app, plist),
        vendor=_vendor(bundle_id),
        team_id=_team_id(app),
        cask=cask,
        zap_paths=zap,
    )
