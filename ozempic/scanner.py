"""
Scanner module for ozempic: heuristic security/hygiene scanning.
No external dependencies — stdlib only.
"""

import os
import subprocess
import time
from pathlib import Path

from ozempic.cleaner import format_size

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOME = Path.home()

_INSTALLER_EXTS = {".dmg", ".pkg", ".zip", ".tar", ".gz", ".tgz", ".app"}

_SCRIPT_EXTS = {".sh", ".py", ".rb", ".pl", ".zsh", ".bash"}

_SKIP_PREFIXES = [
    str(HOME / ".cargo") + os.sep,
    str(HOME / ".rustup") + os.sep,
    str(HOME / ".pyenv") + os.sep,
    str(HOME / ".nvm") + os.sep,
    str(HOME / ".rbenv") + os.sep,
    str(HOME / ".oh-my-zsh") + os.sep,
    str(HOME / ".config") + os.sep,
    str(HOME / ".local") + os.sep,
    str(HOME / "Library") + os.sep,
    str(HOME / "Desktop") + os.sep,
    str(HOME / "Downloads") + os.sep,
    str(HOME / "Documents") + os.sep,
    str(HOME / "Movies") + os.sep,
    str(HOME / "Music") + os.sep,
    str(HOME / "Pictures") + os.sep,
    str(HOME / "Projects") + os.sep,
    str(HOME / "Developer") + os.sep,
    str(HOME / "src") + os.sep,
    str(HOME / "code") + os.sep,
    str(HOME / "repos") + os.sep,
    str(HOME / "workspace") + os.sep,
    str(HOME / "dev") + os.sep,
    "/usr/local/",
    "/opt/homebrew/",
]

KNOWN_HIDDEN = {
    ".zshrc", ".zprofile", ".zshenv", ".bash_profile", ".bashrc", ".bash_history",
    ".profile", ".gitconfig", ".gitignore", ".gitignore_global",
    ".ssh", ".config", ".local", ".npm", ".cargo", ".rustup",
    ".pyenv", ".nvm", ".rbenv", ".oh-my-zsh", ".vscode", ".DS_Store",
    ".Trash", ".claude", ".zsh_sessions", ".zsh_history",
    ".CFUserTextEncoding", ".lesshst",
    ".docker", ".gradle", ".android", ".kube", ".asdf", ".volta",
    ".deno", ".pnpm", ".bun", ".terraform.d", ".aws", ".gcloud",
    ".azure", ".m2", ".ivy2", ".sbt", ".lein", ".boot",
    ".venv", ".virtualenvs", ".poetry", ".rvm",
    ".gem", ".bundle", ".rbenv",
    ".node_repl_history", ".python_history",
    ".mysql_history", ".psql_history", ".rediscli_history",
    ".gitmodules", ".editorconfig", ".npmrc", ".yarnrc",
    ".tool-versions",
}

_DOC_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".docx", ".xlsx", ".pptx", ".txt"}

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif"}

_LARGE_FILE_THRESHOLD = 500 * 1024 * 1024  # 500 MB
_OLD_FILE_DAYS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_path(path: Path) -> str:
    """Return a ~ -abbreviated path string."""
    try:
        return "~/" + str(path.relative_to(HOME))
    except ValueError:
        return str(path)


def _make_result(path: Path, size_str: str) -> dict:
    return {
        "label": _short_path(path),
        "size_str": size_str,
        "action": None,
    }


def _top_level_files(directory: Path):
    """Yield non-symlink files at the top level of *directory*."""
    try:
        for entry in directory.iterdir():
            if entry.is_symlink():
                continue
            if entry.is_file():
                yield entry
    except (PermissionError, FileNotFoundError):
        pass


def _seconds_30_days_ago() -> float:
    return time.time() - _OLD_FILE_DAYS * 86400


# ---------------------------------------------------------------------------
# Layer 1: Location anomalies
# ---------------------------------------------------------------------------

def _scan_1a_executables_in_downloads() -> list[dict]:
    """1a. Executables (non-installer) in ~/Downloads/ (top-level only)."""
    results = []
    downloads = HOME / "Downloads"
    for path in _top_level_files(downloads):
        if path.suffix.lower() in _INSTALLER_EXTS:
            continue
        try:
            if os.access(path, os.X_OK):
                results.append(_make_result(path, "executable file in Downloads"))
        except PermissionError:
            pass
    return results


def _scan_1b_scripts_in_unexpected_places() -> list[dict]:
    """1b. Script files in unexpected locations under ~."""
    results = []
    try:
        for dirpath_str, dirnames, filenames in os.walk(HOME):
            # Prune known-good directories in-place to avoid descending
            dirnames[:] = [
                d for d in dirnames
                if not (dirpath_str == str(HOME) and d == "Library")
            ]

            dirpath = Path(dirpath_str)

            # Skip if this path starts with a known-good prefix
            path_with_sep = str(dirpath) + os.sep
            skip = False
            for prefix in _SKIP_PREFIXES:
                if path_with_sep.startswith(prefix) or str(dirpath) == prefix.rstrip(os.sep):
                    skip = True
                    break
            if skip:
                # Also prune so we don't descend further
                dirnames.clear()
                continue

            for filename in filenames:
                path = dirpath / filename
                try:
                    if path.is_symlink():
                        continue
                    suffix = path.suffix.lower()
                    if suffix not in _SCRIPT_EXTS:
                        continue
                except (PermissionError, OSError):
                    continue
                results.append(_make_result(path, "script file in unexpected location"))
    except PermissionError:
        pass
    return results


def _scan_1c_unexpected_hidden_in_home() -> list[dict]:
    """1c. Unexpected dotfiles/dotdirs directly under ~."""
    results = []
    try:
        for entry in HOME.iterdir():
            if entry.is_symlink():
                continue
            name = entry.name
            if name.startswith(".") and name not in KNOWN_HIDDEN:
                results.append(_make_result(entry, "unexpected hidden item in home directory"))
    except PermissionError:
        pass
    return results


def _scan_1d_large_old_files() -> list[dict]:
    """1d. Large files (>500MB) not modified in 30+ days in Downloads/Desktop."""
    results = []
    cutoff = _seconds_30_days_ago()
    for directory in [HOME / "Downloads", HOME / "Desktop"]:
        for path in _top_level_files(directory):
            try:
                st = path.stat()
                if st.st_size > _LARGE_FILE_THRESHOLD and st.st_mtime < cutoff:
                    size_str = f"large file ({format_size(st.st_size)}) not accessed in 30+ days"
                    results.append(_make_result(path, size_str))
            except (PermissionError, OSError):
                pass
    return results


def scan_location_anomalies() -> list[dict]:
    """Run all Layer 1 location anomaly checks and return combined results."""
    results = []
    results.extend(_scan_1a_executables_in_downloads())
    results.extend(_scan_1b_scripts_in_unexpected_places())
    results.extend(_scan_1c_unexpected_hidden_in_home())
    results.extend(_scan_1d_large_old_files())
    return results


# ---------------------------------------------------------------------------
# Layer 2: Extension mismatches
# ---------------------------------------------------------------------------

def _scan_2a_doc_image_with_exec_bit() -> tuple[list[dict], set]:
    """2a. Document/image files with executable bit in Downloads/Desktop/Documents."""
    results = []
    flagged_paths = set()
    for directory in [HOME / "Downloads", HOME / "Desktop", HOME / "Documents"]:
        for path in _top_level_files(directory):
            ext = path.suffix.lower()
            if ext in _DOC_IMAGE_EXTS:
                try:
                    if os.access(path, os.X_OK):
                        results.append(_make_result(path, f"has executable bit set (extension: {ext})"))
                        flagged_paths.add(path)
                except PermissionError:
                    pass
    return results, flagged_paths


def _scan_2b_extensionless_executables() -> list[dict]:
    """2b. Extensionless executable files in ~/Downloads/ (top-level only)."""
    results = []
    for path in _top_level_files(HOME / "Downloads"):
        if "." not in path.name:
            try:
                if os.access(path, os.X_OK):
                    results.append(_make_result(path, "extensionless executable file"))
            except PermissionError:
                pass
    return results


def _scan_2c_extension_vs_filetype(already_flagged: set) -> list[dict]:
    """2c. Extension vs actual file type mismatch for image files in ~/Downloads/."""
    results = []
    for path in _top_level_files(HOME / "Downloads"):
        if path in already_flagged:
            continue
        ext = path.suffix.lower()
        if ext not in _IMAGE_EXTS:
            continue
        try:
            proc = subprocess.run(
                ["file", "-b", str(path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = proc.stdout.strip()
            if not output:
                continue

            matched = False
            if ext in (".jpg", ".jpeg"):
                matched = "JPEG" in output
            elif ext == ".png":
                matched = "PNG" in output
            elif ext == ".gif":
                matched = "GIF" in output

            if not matched:
                actual_type = output.split()[0] if output.split() else output
                results.append(_make_result(
                    path,
                    f"extension mismatch: declared {ext}, detected {actual_type}",
                ))
        except (PermissionError, subprocess.TimeoutExpired, OSError):
            pass
    return results


def scan_extension_mismatches() -> list[dict]:
    """Run all Layer 2 extension mismatch checks and return combined results."""
    results_2a, flagged_2a = _scan_2a_doc_image_with_exec_bit()
    results_2b = _scan_2b_extensionless_executables()
    results_2c = _scan_2c_extension_vs_filetype(flagged_2a)
    return results_2a + results_2b + results_2c


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_all() -> list[dict]:
    """Run all scans and return combined results."""
    return scan_location_anomalies() + scan_extension_mismatches()
