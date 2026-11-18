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
    except Exception:  # OSError, InvalidFileException, ExpatError (truncated XML), ...
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
        return [p.absolute()]
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


# ---------------------------------------------------------------------------
# Leftover matching
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    path: Path
    group: str
    reason: str
    checked: bool
    size: int


@dataclass
class OtherApps:
    ids: set[str]
    names: set[str]
    paths: list[Path]


# (relative path under Library, kind). Kind drives the extra rules:
# "support" = exact-name eligible, "launchd", "group", "crash", "" = id rules only.
_USER_LOCATIONS = (
    ("Application Support", "support"),
    ("Caches", "support"),
    ("Preferences", ""),
    ("Preferences/ByHost", ""),
    ("Containers", ""),
    ("Group Containers", "group"),
    ("Saved Application State", ""),
    ("Logs", "support"),
    ("HTTPStorages", ""),
    ("WebKit", ""),
    ("Cookies", ""),
    ("Application Scripts", ""),
    ("LaunchAgents", "launchd"),
    ("Logs/DiagnosticReports", "crash"),
)
_SYSTEM_LOCATIONS = (
    ("Application Support", "support"),
    ("Caches", "support"),
    ("Preferences", ""),
    ("LaunchAgents", "launchd"),
    ("LaunchDaemons", "launchd"),
    ("PrivilegedHelperTools", ""),
    ("Logs", "support"),
    ("Logs/DiagnosticReports", "crash"),
)

_GROUP_PREFIX = re.compile(r"^(?:group\.)?(?:([A-Z0-9]{10})\.)?(.+)$")


def strip_group_prefix(name: str) -> tuple[str, str | None]:
    """Strip a leading 'group.' and/or '<TEAMID>.' from a Group Container name."""
    m = _GROUP_PREFIX.match(name)
    return m.group(2), m.group(1)


def other_apps(roots: Roots, exclude: Path) -> OtherApps:
    """IDs and names of every installed app except *exclude*."""
    ex = exclude.resolve()
    ids: set[str] = set()
    names: set[str] = set()
    paths: list[Path] = []
    for app in _iter_apps(roots):
        if app.resolve() == ex:
            continue
        plist = _bundle_plist(app)
        if not plist or not isinstance(plist.get("CFBundleIdentifier"), str):
            continue
        bid = plist["CFBundleIdentifier"]
        ids.add(bid.lower())
        ids.update(h.lower() for h in _helper_ids(app, bid))
        names.update(_name_keys(app, plist))
        paths.append(app)
    return OtherApps(ids=ids, names=names, paths=paths)


def _id_match(name: str, ident: str) -> bool:
    return name == ident or name.startswith(ident + ".")


def _longest_match(name: str, idents) -> str | None:
    best = None
    for ident in idents:
        if _id_match(name, ident) and (best is None or len(ident) > len(best)):
            best = ident
    return best


def _launchd_targets_app(plist_path: Path, app: Path) -> bool:
    data = _read_plist(plist_path)
    if not data:
        return False
    program = data.get("Program")
    if not isinstance(program, str):
        args = data.get("ProgramArguments")
        program = args[0] if isinstance(args, list) and args and isinstance(args[0], str) else ""
    return program.startswith(str(app) + "/")


def find_candidates(info: AppInfo, others: OtherApps, roots: Roots) -> list[Candidate]:
    """Every leftover of *info*, one Candidate per path, with its default check state."""
    from ozempic.cleaner import get_size

    bundle_id = info.bundle_id.lower()
    helpers = [h.lower() for h in info.helper_ids]
    target_ids = [bundle_id, *helpers]
    vendor_prefix = ".".join(bundle_id.split(".")[:2])
    keys = [k for k in info.names if len(k) >= 4]
    partial_keys = keys + ([info.vendor] if info.vendor and len(info.vendor) >= 4 else [])
    crash_keys = [*info.names, *target_ids]

    locations = [(roots.home / "Library" / rel, f"~/Library/{rel}", kind)
                 for rel, kind in _USER_LOCATIONS]
    locations += [(roots.system_library / rel, f"/Library/{rel}", kind)
                  for rel, kind in _SYSTEM_LOCATIONS]
    location_roots = {loc for loc, _, _ in locations}
    group_order = ["Application"] + [label for _, label, _ in locations] + ["Homebrew"]

    found: dict[Path, Candidate] = {}

    def add(path: Path, group: str, reason: str, checked: bool) -> None:
        if path not in found:
            found[path] = Candidate(path, group, reason, checked, get_size(path))

    def group_of(path: Path) -> str:
        for loc, label, _ in locations:
            if path.parent == loc:
                return label
        parent = str(path.parent)
        home = str(roots.home)
        return "~" + parent[len(home):] if parent.startswith(home) else parent

    team_shared: list[bool] = []  # lazy cache: codesign every other app only if needed

    def shares_team() -> bool:
        if not team_shared:
            team_shared.append(any(_team_id(p) == info.team_id for p in others.paths))
        return team_shared[0]

    def exact_name(n: str) -> bool:
        return any(k in (n, Path(n).stem) for k in keys if k not in others.names)

    def zap_checked(z: Path) -> bool:
        """A curated zap path starts checked only if it is clearly this app's own."""
        if not any(z.is_relative_to(loc) for loc in location_roots):
            return False  # outside ~/Library and /Library, e.g. ~/.docker shared with the CLI
        r = strip_group_prefix(z.name)[0].lower()
        own = _longest_match(r, target_ids)
        other = _longest_match(r, others.ids)
        if other and (own is None or len(other) >= len(own)):
            return False
        return bool(own) or exact_name(r)

    # 1. Seeds: the app, curated brew zap paths, the Caskroom entry.
    add(info.path, "Application", "app", True)
    for z in info.zap_paths:
        if z == roots.home or any(loc.is_relative_to(z) for loc in location_roots):
            continue
        ok = zap_checked(z)
        add(z, group_of(z), "brew zap" if ok else "brew zap (shared?)", ok)
    if info.cask:
        cr = roots.caskroom / info.cask
        if cr.exists():
            add(cr, "Homebrew", "cask", True)

    for loc, label, kind in locations:
        try:
            entries = sorted(loc.iterdir())
        except OSError:
            continue
        for e in entries:
            if e in found:
                continue
            n = e.name.lower()
            team = None
            r = n
            if kind == "group":
                rest, team = strip_group_prefix(e.name)
                r = rest.lower()

            # 2. Never Apple's.
            if r.startswith("com.apple.") or n.startswith("com.apple."):
                continue
            # 3. Belongs to another installed app (its ID is a longer match).
            own = _longest_match(r, target_ids)
            other = _longest_match(r, others.ids)
            if other and (own is None or len(other) > len(own)):
                continue
            # 4. Bundle ID / helper ID (unchecked if another installed app owns the same ID).
            if own:
                reason = "bundle id" if own == bundle_id else "helper"
                shared = other is not None and len(other) == len(own)
                add(e, label, f"{reason} (shared)" if shared else reason, not shared)
                continue
            # 5. launchd job pointing inside the app.
            if kind == "launchd" and e.suffix == ".plist" and _launchd_targets_app(e, info.path):
                add(e, label, "launchd", True)
                continue
            # 6. Exact app name.
            if kind == "support":
                stem = Path(n).stem
                hit = next((k for k in info.names if k in (n, stem)), None)
                if hit:
                    ambiguous = len(hit) < 4 or hit in others.names
                    add(e, label, "name (ambiguous)" if ambiguous else "name", not ambiguous)
                    continue
            # 7. Group Containers: Team ID, then vendor prefix.
            if kind == "group":
                if team and info.team_id and team == info.team_id:
                    shared = shares_team()
                    add(e, label, "team (shared)" if shared else "team", not shared)
                    continue
                if _id_match(r, vendor_prefix):
                    add(e, label, "vendor (shared)", False)
                    continue
            # 8. Crash reports.
            if kind == "crash" and any(
                n.startswith(k) and len(n) > len(k) and n[len(k)] in "-_. " for k in crash_keys
            ):
                add(e, label, "crash report", True)
                continue
            # 9. Partial match.
            if any(k in n for k in partial_keys):
                add(e, label, "partial", False)

    order = {g: i for i, g in enumerate(group_order)}
    return sorted(found.values(), key=lambda c: (order.get(c.group, len(order)), str(c.path)))
