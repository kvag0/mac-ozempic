"""
Reporter module for ozempic: ANSI-colored structured terminal output.
No external dependencies — stdlib only.
"""

import sys
import threading
import time

# ANSI color codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"


def _calculate_total_size(results: list[dict]) -> str:
    """
    Calculate total size from results, summing all size_str values.
    Handles both GB/MB and file counts.
    Returns human-readable total.

    Priority: If any size is in GB/MB, convert all to GB and sum.
    Otherwise, if all are file counts, sum the files.
    """
    total_gb = 0.0
    total_files = 0
    has_size_units = False

    for result in results:
        size_str = result.get("size_str", "")
        if "GB" in size_str:
            try:
                total_gb += float(size_str.replace(" GB", ""))
                has_size_units = True
            except ValueError:
                pass
        elif "MB" in size_str:
            try:
                total_gb += float(size_str.replace(" MB", "")) / 1024
                has_size_units = True
            except ValueError:
                pass
        elif "KB" in size_str:
            try:
                total_gb += float(size_str.replace(" KB", "")) / (1024 * 1024)
                has_size_units = True
            except ValueError:
                pass
        elif size_str.endswith(" B") and not size_str.endswith("GB") and not size_str.endswith("KB") and not size_str.endswith("MB"):
            try:
                total_gb += float(size_str.replace(" B", "")) / (1024 ** 3)
                has_size_units = True
            except ValueError:
                pass
        elif "files" in size_str:
            try:
                total_files += int(size_str.replace(" files", ""))
            except ValueError:
                pass

    size_part = ""
    if has_size_units and total_gb > 0:
        size_part = f"{total_gb:.1f} GB" if total_gb >= 1 else f"{int(total_gb * 1024)} MB"

    if size_part and total_files > 0:
        return f"{size_part} and {total_files} files"
    if size_part:
        return size_part
    if total_files > 0:
        return f"{total_files} files"
    return "0 B"


def _align_columns(results: list[dict]) -> list[tuple[str, str, str | None]]:
    """
    Align label and size_str columns to consistent width within a section.
    Returns list of (label, size_str, action) tuples with padded labels.
    Caps label width to prevent extremely wide terminals.
    """
    if not results:
        return []

    # Calculate max label width, capped at 60
    max_label_width = 45
    found_max = max(len(r.get("label", "")) for r in results)
    actual_width = min(found_max, max_label_width)

    aligned = []
    for result in results:
        label = result.get("label", "")
        size_str = result.get("size_str", "")
        action = result.get("action")

        # Truncate label in the middle if too long
        if len(label) > max_label_width:
            prefix = label[:20]
            suffix = label[-22:]
            display_label = f"{prefix}...{suffix}"
        else:
            display_label = label

        padded_label = display_label.ljust(actual_width)
        aligned.append((padded_label, size_str, action))

    return aligned


def _format_header(title: str, color: str) -> tuple[str, int]:
    """
    Format a section header with colored title and box-drawing character.
    Returns (formatted_header_str, header_width_for_separator).
    """
    # Create header: "━━━ TITLE ━━━..."
    # The total width should be ~45 characters (approx project default)
    title_text = f" {title} "
    remaining = 45 - len(title_text) - 2  # 2 for leading "━━━"
    left_dashes = 2
    right_dashes = remaining - left_dashes

    header = f"{color}{'━' * left_dashes}{BOLD}{title_text}{RESET}{color}{'━' * right_dashes}{RESET}"
    return header, 45


def print_cleaned(results: list[dict]) -> None:
    """
    Print the CLEANED section with green header, green checkmarks, and total.
    Format:
      ━━━ CLEANED ━━━━━━━━━━━━━━━━━━━━━━━━━━
        ✓ User caches          1.2 GB
        ─────────────────────────────────────
        Total freed: 1.8 GB
    """
    header, header_width = _format_header("CLEANED", GREEN)
    print()
    print(header)

    if not results:
        print("  (nothing found)")
        print()
        return

    aligned = _align_columns(results)
    for label, size_str, _ in aligned:
        print(f"  {GREEN}✓{RESET} {label}  {size_str}")

    # Separator line
    separator = "─" * (header_width - 2)  # -2 for padding
    print(f"  {separator}")

    # Total line
    total_size = _calculate_total_size(results)
    print(f"  Total freed: {total_size}")
    print()


def print_review(results: list[dict]) -> None:
    """
    Print the REVIEW section with yellow header and warning symbols.
    Action field can be multi-line (e.g., iOS backup has device name + command).
    Format:
      ━━━ REVIEW ━━━━━━━━━━━━━━━━━━━━━━━━━━
        ⚠ Trash                4.1 GB  →  run: rm -rf ~/.Trash/*
        ⚠ iOS backup           12 GB   →  "Caio's iPhone" (2026-04-01)
                                          run: ozempic --delete-backup <id>
    """
    header, _ = _format_header("REVIEW", YELLOW)
    print()
    print(header)

    if not results:
        print("  (nothing found)")
        print()
        return

    aligned = _align_columns(results)
    for label, size_str, action in aligned:
        first_line = f"  {YELLOW}⚠{RESET} {label}  {size_str}"
        if action:
            first_line += f"  →  {action.split(chr(10))[0] if chr(10) in action else action}"
        print(first_line)

        # Print remaining lines of multi-line actions
        if action and "\n" in action:
            lines = action.split("\n")
            # Calculate indent: 2 spaces + 1 char symbol + 1 space + padded label + 2 spaces + size_str + "  →  "
            # The first_line without color codes: "  ⚠ " + label + "  " + size_str + "  →  "
            prefix_width = 2 + 1 + 1 + len(label) + 2 + len(size_str) + 5  # 5 for "  →  "
            indent = " " * prefix_width
            for line in lines[1:]:
                print(f"{indent}{line}")

    print()


class Spinner:
    """A simple threaded CLI spinner."""
    def __init__(self, message: str = "Analyzing"):
        self.message = message
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._stop_event = threading.Event()
        self._thread = None

    def _spin(self):
        idx = 0
        while not self._stop_event.is_set():
            frame = self.frames[idx % len(self.frames)]
            sys.stdout.write(f"\r  {CYAN}{frame}{RESET} {self.message}...")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)
        # Clear the line on exit
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin)
        self._thread.daemon = True
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._thread:
            self._thread.join()


def print_fda_error() -> None:
    """
    Print error message explaining FDA requirement and how to enable it.
    """
    print()
    print(f"{RED}{BOLD}FDA_ERROR: Full Disk Access Required{RESET}")
    print()
    print(f"  {RED}ozempic{RESET} needs Full Disk Access to scan and clean your disk.")
    print()
    print(f"  To enable, follow these steps:")
    print(f"    1. Open System Settings")
    print(f"    2. Go to Privacy & Security")
    print(f"    3. Select Full Disk Access")
    print(f"    4. Add {RED}Terminal{RESET} (or your shell environment)")
    print()
    print(f"  Then try running {RED}ozempic{RESET} again.")
    print()
