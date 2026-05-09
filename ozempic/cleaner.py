"""
Cleaner module for ozempic: disk cleaning logic.
No external dependencies — stdlib only.
"""

import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# FDA check
# ---------------------------------------------------------------------------

def check_fda() -> bool:
    """
    Return True if Full Disk Access is available.

    Tries to open the TCC database. If we get an OperationalError the process
    does not have FDA. If we can open it (even if our terminal is not listed)
    we consider FDA granted — the mere ability to open the file proves it.
    """
    tcc_db = Path("/Library/Application Support/com.apple.TCC/TCC.db")
    try:
        con = sqlite3.connect(f"file:{tcc_db}?mode=ro", uri=True)
        con.execute(
            "SELECT client FROM access WHERE service = 'kTCCServiceSystemPolicyAllFiles'"
        ).fetchall()
        con.close()
        return True
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Size helpers
# ---------------------------------------------------------------------------

def get_size(path: Path) -> int:
    """Return the recursive byte count of *path* (file or directory)."""
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for fname in filenames:
            try:
                total += Path(dirpath, fname).stat().st_size
            except OSError:
                pass
    return total


def format_size(n_bytes: int) -> str:
    """
    Return a human-readable size string.

    NOTE: This function also accepts a *file count* in callers that track
    counts rather than bytes — in that case the caller should call it with
    ``format_size`` **not** being used; instead the caller produces the
    ``"N files"`` string directly.  This function only handles byte counts.
    """
    if n_bytes >= 1_073_741_824:  # 1 GB
        return f"{n_bytes / 1_073_741_824:.1f} GB"
    if n_bytes >= 1_048_576:  # 1 MB
        return f"{n_bytes / 1_048_576:.0f} MB"
    if n_bytes >= 1_024:
        return f"{n_bytes / 1_024:.0f} KB"
    return f"{n_bytes} B"


# ---------------------------------------------------------------------------
# Low-level deletion helpers
# ---------------------------------------------------------------------------

def _delete_dir_contents(path: Path) -> None:
    """Delete all items inside *path* without deleting the folder itself."""
    if not path.is_dir():
        return
    for item in path.iterdir():
        try:
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
        except PermissionError:
            pass
        except OSError:
            pass


def _delete_path(path: Path) -> None:
    """Delete a file or directory tree, ignoring PermissionError."""
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except PermissionError:
        pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Individual cleaning targets
# ---------------------------------------------------------------------------

def _clean_dir_contents(label: str, path: Path, dry_run: bool = False) -> dict | None:
    """
    Measure *path*, delete its contents (if not dry_run), return a result dict.
    Returns None if path does not exist.
    """
    path = path.expanduser()
    if not path.exists():
        return None
    size = get_size(path)
    if size == 0:
        return None
    if not dry_run:
        try:
            _delete_dir_contents(path)
        except PermissionError:
            return None
    return {"label": label, "size_str": format_size(size), "action": None}


def _clean_path(label: str, path: Path, dry_run: bool = False) -> dict | None:
    """
    Measure *path*, delete it entirely (if not dry_run), return a result dict.
    Returns None if path does not exist.
    """
    path = path.expanduser()
    if not path.exists():
        return None
    size = get_size(path)
    if size == 0:
        return None
    if not dry_run:
        try:
            _delete_path(path)
        except PermissionError:
            return None
    return {"label": label, "size_str": format_size(size), "action": None}


def _clean_electron_sub_caches(dry_run: bool = False) -> list[dict]:
    """
    Walk ~/Library/Application Support/. For each app subdirectory look for
    GPUCache, Code Cache, or CachedData subdirectories and clean their contents.
    Skip any folder named com.apple.bird or with CloudKit in its path.
    """
    base = Path("~/Library/Application Support").expanduser()
    if not base.is_dir():
        return []

    results: list[dict] = []
    target_names = {"GPUCache", "Code Cache", "CachedData"}

    for app_dir in base.iterdir():
        if not app_dir.is_dir():
            continue
        if app_dir.name == "com.apple.bird":
            continue
        if "CloudKit" in str(app_dir):
            continue
        try:
            subdirs = list(app_dir.iterdir())
        except PermissionError:
            continue
        for sub in subdirs:
            if not sub.is_dir():
                continue
            if sub.name not in target_names:
                continue
            if "CloudKit" in str(sub):
                continue
            size = get_size(sub)
            if size == 0:
                continue
            if not dry_run:
                try:
                    _delete_dir_contents(sub)
                except PermissionError:
                    continue
            results.append({
                "label": f"{app_dir.name} ({sub.name})",
                "size_str": format_size(size),
                "action": None,
            })

    return results


def _clean_mail_downloads(dry_run: bool = False) -> dict | None:
    """Find Mail Downloads directories and delete their contents (if not dry_run)."""
    base = Path("~/Library/Containers/com.apple.mail").expanduser()
    if not base.exists():
        return None

    total_size = 0
    found = False
    for mail_dl in base.rglob("Mail Downloads"):
        if not mail_dl.is_dir():
            continue
        found = True
        total_size += get_size(mail_dl)
        if not dry_run:
            _delete_dir_contents(mail_dl)

    if not found or total_size == 0:
        return None
    return {"label": "Mail Downloads", "size_str": format_size(total_size), "action": None}


def _clean_ds_store(dry_run: bool = False) -> dict | None:
    """Find and delete all .DS_Store files under ~. Return file count (if not dry_run)."""
    home = Path.home()
    count = 0
    for dirpath, dirnames, filenames in os.walk(home, followlinks=False):
        # Avoid descending into Library/Application Support/com.apple.bird
        dirnames[:] = [
            d for d in dirnames
            if not ("com.apple.bird" == d or "CloudKit" in os.path.join(dirpath, d))
        ]
        for fname in filenames:
            if fname == ".DS_Store":
                count += 1
                if not dry_run:
                    try:
                        Path(dirpath, fname).unlink()
                    except (PermissionError, OSError):
                        pass
    if count == 0:
        return None
    return {"label": ".DS_Store files", "size_str": f"{count} files", "action": None}


def _run_quicklook_cache() -> dict:
    result = subprocess.run(["qlmanage", "-r", "cache"], capture_output=True, timeout=30)
    size_str = "cleared" if result.returncode == 0 else "reset attempted (error)"
    return {"label": "QuickLook cache", "size_str": size_str, "action": None}


def _run_font_cache() -> dict:
    result = subprocess.run(
        ["atsutil", "databases", "-removeUser"], capture_output=True, timeout=30
    )
    size_str = "cleared" if result.returncode == 0 else "reset attempted (error)"
    return {"label": "Font cache", "size_str": size_str, "action": None}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_all(keep_logs: bool = False, dry_run: bool = False) -> list[dict]:
    """
    Run all auto-delete targets.  Returns a list of result dicts compatible
    with reporter.py (only non-None / non-zero results are included).
    """
    results: list[dict] = []

    def _add(item: dict | None) -> None:
        if item is not None:
            results.append(item)

    # User caches (delete contents, keep folder)
    _add(_clean_dir_contents("User caches", Path("~/Library/Caches"), dry_run))

    # System caches (may need sudo — skip on PermissionError)
    sys_caches = Path("/Library/Caches")
    if sys_caches.exists():
        size = get_size(sys_caches)
        if size > 0:
            if not dry_run:
                try:
                    _delete_dir_contents(sys_caches)
                    results.append({"label": "System caches", "size_str": format_size(size), "action": None})
                except PermissionError:
                    pass
            else:
                results.append({"label": "System caches", "size_str": format_size(size), "action": None})

    # Logs
    if not keep_logs:
        _add(_clean_dir_contents("User logs", Path("~/Library/Logs"), dry_run))
        sys_logs = Path("/Library/Logs")
        if sys_logs.exists():
            size = get_size(sys_logs)
            if size > 0:
                if not dry_run:
                    try:
                        _delete_dir_contents(sys_logs)
                        results.append({"label": "System logs", "size_str": format_size(size), "action": None})
                    except PermissionError:
                        pass
                else:
                    results.append({"label": "System logs", "size_str": format_size(size), "action": None})

    # Xcode derived data
    _add(_clean_dir_contents(
        "Xcode derived data",
        Path("~/Library/Developer/Xcode/DerivedData"),
        dry_run,
    ))

    # npm cache
    _add(_clean_path("npm cache", Path("~/.npm/_cacache"), dry_run))

    # pip cache
    _add(_clean_path("pip cache", Path("~/Library/Caches/pip"), dry_run))

    # Homebrew cache
    _add(_clean_path("Homebrew cache", Path("~/Library/Caches/Homebrew"), dry_run))

    # Electron sub-caches
    results.extend(_clean_electron_sub_caches(dry_run))

    # Mail Downloads
    _add(_clean_mail_downloads(dry_run))

    # Commands (QL and Fonts) - Skip in dry run or report as "to be cleared"
    if not dry_run:
        # QuickLook cache
        try:
            results.append(_run_quicklook_cache())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Font cache
        try:
            results.append(_run_font_cache())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    else:
        results.append({"label": "QuickLook cache", "size_str": "pending", "action": None})
        results.append({"label": "Font cache", "size_str": "pending", "action": None})

    # .DS_Store files
    _add(_clean_ds_store(dry_run))

    return results


def get_review_items() -> list[dict]:
    """
    Return review items: Trash.
    Each item is a result dict compatible with reporter.py.
    """
    results: list[dict] = []

    # Trash
    trash = Path("~/.Trash").expanduser()
    if trash.exists():
        size = get_size(trash)
        if size > 0:
            results.append({
                "label": "Trash",
                "size_str": format_size(size),
                "action": "run: rm -rf ~/.Trash/*",
            })

    return results


