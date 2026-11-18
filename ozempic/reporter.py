"""
Reporter module for ozempic: ANSI-colored structured terminal output.
No external dependencies — stdlib only.
"""

import sys
import threading
import time
import re

# ANSI color codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"

# Emojis/icons for each cleanup category
ICONS = {
    "User caches": "📂",
    "System caches": "⚙️",
    "User logs": "📝",
    "System logs": "📋",
    "Xcode derived data": "🛠️",
    "npm cache": "📦",
    "pip cache": "🐍",
    "Homebrew cache": "🍺",
    "Mail Downloads": "✉️",
    "QuickLook cache": "👁️",
    "Font cache": "🔤",
    ".DS_Store files": "🧹",
    "Trash": "🗑️",
    "iOS backup": "📱",
}


def get_icon(label: str) -> str:
    """Return appropriate emoji icon for the given category label."""
    # Check exact matches first
    if label in ICONS:
        return ICONS[label]
    
    # Check partial matches
    for key, icon in ICONS.items():
        if key in label:
            return icon
            
    # Electron or generic apps
    if "GPUCache" in label or "Code Cache" in label or "CachedData" in label:
        return "⚛️"
        
    return "📄"


def _visible_len(text: str) -> int:
    """Calculate the visible character/cell width of text, ignoring ANSI escape sequences and accounting for emojis."""
    clean_text = re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', text)
    val = len(clean_text)
    # Add 1 for double-width emojis/indicators
    emojis = "📂⚙️📝📋🛠️📦🐍🍺✉️👁️🔤🧹🗑️📱⚛️📄🟢🟡✨⚠️❌✓✗"
    for char in clean_text:
        if char in emojis:
            val += 1
    return val


def print_logo() -> None:
    """Print the colored gradient ASCII art banner for ozempic."""
    logo_lines = [
        "  ____                      _      ",
        " / __ \\___ ___ __ _  _ __  (_)___  ",
        "/ /_/ /_ // -_)  ' \\| '_ \\/ / __/  ",
        "\\____//___\\__/_/_/_/ .__/_/\\___/   ",
        "                   /_/             "
    ]
    colors = [
        "\033[38;5;51m",  # Bright Cyan
        "\033[38;5;45m",  # Blue-Cyan
        "\033[38;5;99m",  # Purple-Blue
        "\033[38;5;201m", # Magenta
        "\033[38;5;207m"  # Pink
    ]
    print()
    for line, color in zip(logo_lines, colors):
        print(f" {color}{line}{RESET}")
    print(f"  {CYAN}macOS Disk Cleaner{RESET} • {YELLOW}v1.0.0{RESET}")
    print(f"  {BOLD}Let's keep your Mac healthy and lean!{RESET}")
    print()


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


def _print_card(title: str, results: list[dict], total_label: str = None, total_val: str = None, is_review: bool = False) -> None:
    """Print results in a beautifully styled terminal card with double/single line borders."""
    width = 58
    border_color = YELLOW if is_review else GREEN
    
    # Top border
    print(f"{border_color}┌{'─' * (width - 2)}┐{RESET}")
    
    # Title line
    title_icon = "⚠️" if is_review else "🟢"
    title_text = f"  {title_icon}  {BOLD}{title}{RESET}"
    title_len = _visible_len(title_text)
    right_pad = width - 2 - title_len
    print(f"{border_color}│{RESET}{title_text}{' ' * right_pad}{border_color}│{RESET}")
    
    # Separator
    print(f"{border_color}├{'─' * (width - 2)}┤{RESET}")
    
    if not results:
        empty_text = "  (nothing found)"
        empty_len = _visible_len(empty_text)
        right_pad = width - 2 - empty_len
        print(f"{border_color}│{RESET}{empty_text}{' ' * right_pad}{border_color}│{RESET}")
    else:
        # Format items inside card
        for result in results:
            label = result.get("label", "")
            size_str = result.get("size_str", "")
            action = result.get("action")
            
            icon = get_icon(label.strip())
            clean_label = label.strip()
            
            # Truncate clean_label if it's too long to fit
            max_label_len = width - 2 - 4 - len(size_str) - 4
            if _visible_len(clean_label) > max_label_len:
                clean_label = clean_label[:max_label_len - 3] + "..."
            
            icon_str = f"  {icon} "
            item_text = f"{icon_str}{clean_label}"
            item_len = _visible_len(item_text)
            
            # Pad spaces to align size_str to the right
            spaces_count = width - 2 - item_len - _visible_len(size_str) - 2
            line_str = f"{item_text}{' ' * spaces_count}{size_str}  "
            
            print(f"{border_color}│{RESET}{line_str}{border_color}│{RESET}")
            
            # Handle multi-line commands or review actions
            if action:
                lines = action.split("\n")
                for sub_line in lines:
                    sub_text = f"     ↳ {sub_line}"
                    sub_len = _visible_len(sub_text)
                    right_pad_sub = width - 2 - sub_len
                    print(f"{border_color}│{RESET}{YELLOW}{sub_text}{RESET}{' ' * right_pad_sub}{border_color}│{RESET}")
                    
    # Print total summary if provided
    if total_label and total_val:
        print(f"{border_color}├{'─' * (width - 2)}┤{RESET}")
        total_text = f"  ✨ {total_label}: {BOLD}{GREEN}{total_val}{RESET}"
        total_len = _visible_len(total_text)
        right_pad_tot = width - 2 - total_len
        print(f"{border_color}│{RESET}{total_text}{' ' * right_pad_tot}{border_color}│{RESET}")
        
    # Bottom border
    print(f"{border_color}└{'─' * (width - 2)}┘{RESET}")


def print_cleaned(results: list[dict]) -> None:
    """Print the CLEANED section in a card layout."""
    print()
    total_freed = _calculate_total_size(results)
    _print_card("CLEANED TARGETS", results, total_label="Total Freed", total_val=total_freed, is_review=False)
    print()


def print_review(results: list[dict]) -> None:
    """Print the REVIEW section in a card layout."""
    print()
    _print_card("ITEMS TO REVIEW", results, is_review=True)
    print()


class Spinner:
    """A thread-safe CLI spinner with progress messages and clean line updates."""
    def __init__(self, message: str = "Analyzing"):
        self.message = message
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def update_message(self, new_message: str) -> None:
        """Update the spinner message thread-safely."""
        with self._lock:
            self.message = new_message

    def _spin(self):
        idx = 0
        last_len = 0
        while not self._stop_event.is_set():
            frame = self.frames[idx % len(self.frames)]
            with self._lock:
                msg = self.message
            
            line = f"\r  {CYAN}{frame}{RESET} {msg}..."
            visible_len = _visible_len(line)
            
            padding = max(0, last_len - visible_len)
            sys.stdout.write(line + " " * padding)
            sys.stdout.flush()
            
            last_len = visible_len + padding
            idx += 1
            time.sleep(0.1)
            
        # Clear the spinner line completely
        sys.stdout.write("\r" + " " * last_len + "\r")
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


def print_candidates(info, items) -> None:
    """Dry-run listing of what `ozempic uninstall` found, grouped by location."""
    from ozempic.cleaner import format_size

    checked = [c for c in items if c.checked]
    print()
    print(f"  {BOLD}{info.path.stem}{RESET} ({info.bundle_id}) · {len(items)} items · "
          f"{GREEN}{format_size(sum(c.size for c in checked))}{RESET} checked")
    last = None
    for c in items:
        if c.group != last:
            print(f"\n  {CYAN}▸ {c.group}{RESET}")
            last = c.group
        label = str(c.path) if c.group in ("Application", "Homebrew") else c.path.name
        mark = f"{GREEN}[x]{RESET}" if c.checked else "[ ]"
        print(f"    {mark} {label:<48} {format_size(c.size):>8}  {YELLOW}{c.reason}{RESET}")
    print(f"\n  Dry run: nothing was moved. {len(checked)} of {len(items)} items would go to the Trash.\n")


def print_uninstalled(removed, failed) -> None:
    """Result cards after `ozempic uninstall` moved items to the Trash."""
    from ozempic.cleaner import format_size

    print()
    results = [{"label": c.path.name, "size_str": format_size(c.size), "action": None}
               for c in removed]
    _print_card("UNINSTALLED", results, total_label="Moved to Trash",
                total_val=format_size(sum(c.size for c in removed)))
    if failed:
        print()
        _print_card("NOT REMOVED",
                    [{"label": p.name, "size_str": "", "action": reason} for p, reason in failed],
                    is_review=True)
    print()
