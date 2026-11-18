"""
Interactive curses checklist for ozempic uninstall.
No external dependencies — stdlib only.
"""

from __future__ import annotations

import os

from ozempic.cleaner import format_size
from ozempic.uninstaller import AppInfo, Candidate


class ChecklistState:
    """Selection and scroll state, independent of curses."""

    def __init__(self, items: list[Candidate]):
        self.items = items
        self.cursor = 0
        self.offset = 0
        # Display rows: a header before each group's first item.
        self.rows: list[tuple[str, object]] = []
        last = None
        for i, c in enumerate(items):
            if c.group != last:
                self.rows.append(("header", c.group))
                last = c.group
            self.rows.append(("item", i))
        self._row_of = {idx: r for r, (kind, idx) in enumerate(self.rows) if kind == "item"}

    def move(self, delta: int) -> None:
        if self.items:
            self.cursor = max(0, min(len(self.items) - 1, self.cursor + delta))

    def toggle(self) -> None:
        if self.items:
            c = self.items[self.cursor]
            c.checked = not c.checked

    def set_all(self, value: bool) -> None:
        for c in self.items:
            c.checked = value

    def selected(self) -> list[Candidate]:
        return [c for c in self.items if c.checked]

    def selected_size(self) -> int:
        return sum(c.size for c in self.selected())

    def scroll(self, height: int) -> None:
        """Adjust offset (in display rows) so the cursor row is visible."""
        if not self.items or height < 1:
            return
        row = self._row_of[self.cursor]
        top = row - 1 if row > 0 and self.rows[row - 1][0] == "header" else row
        if top < self.offset:
            self.offset = top
        elif row >= self.offset + height:
            self.offset = row - height + 1


def truncate_middle(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width < 2:
        return text[:width]
    head = (width - 1) // 2
    tail = width - 1 - head
    return text[:head] + "…" + text[-tail:]


_FOOTER = "↑↓/jk move · space toggle · a all · n none · enter review · q quit"


def run_checklist(info: AppInfo, items: list[Candidate]) -> list[Candidate] | None:
    """Show the checklist; return the confirmed selection, or None if the user quit."""
    import curses

    os.environ.setdefault("ESCDELAY", "25")
    state = ChecklistState(items)
    return curses.wrapper(_loop, info, state)


def _colors():
    import curses

    attrs = {"header": curses.A_BOLD, "cursor": curses.A_REVERSE, "dim": curses.A_DIM}
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        if curses.COLORS >= 256:
            # Same 256-color indexes as the ozempic logo gradient.
            curses.init_pair(1, 51, bg)
            curses.init_pair(2, 201, bg)
            curses.init_pair(3, 207, bg)
            attrs["header"] = curses.color_pair(1) | curses.A_BOLD
            attrs["cursor"] = curses.color_pair(2) | curses.A_REVERSE
            attrs["dim"] = curses.color_pair(3) | curses.A_DIM
    return attrs


def _put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    import curses

    h, w = win.getmaxyx()
    if 0 <= y < h and x < w:
        try:
            win.addnstr(y, x, text, w - x - (1 if y == h - 1 else 0), attr)
        except curses.error:
            pass


def _label(c: Candidate) -> str:
    return str(c.path) if c.group in ("Application", "Homebrew") else c.path.name


def _draw(win, info: AppInfo, state: ChecklistState, attrs) -> None:
    h, w = win.getmaxyx()
    win.erase()
    head = (f" ozempic uninstall · {info.path.stem} ({info.bundle_id}) · "
            f"{len(state.items)} items · {format_size(state.selected_size())} selected")
    _put(win, 0, 0, head, attrs["header"])
    list_h = max(1, h - 4)
    state.scroll(list_h)
    for y, (kind, val) in enumerate(state.rows[state.offset:state.offset + list_h], start=2):
        if kind == "header":
            _put(win, y, 1, f"▸ {val}", attrs["header"])
            continue
        c = state.items[val]
        size = format_size(c.size)
        right = f"{size:>8}  {c.reason:<16}"
        name_w = max(4, w - len(right) - 10)
        line = f"   [{'x' if c.checked else ' '}] {truncate_middle(_label(c), name_w):<{name_w}} {right}"
        attr = attrs["cursor"] if val == state.cursor else (0 if c.checked else attrs["dim"])
        _put(win, y, 0, line, attr)
    _put(win, h - 1, 1, _FOOTER, attrs["dim"])
    win.refresh()


def _confirm(win, state: ChecklistState, attrs) -> bool:
    h, _ = win.getmaxyx()
    win.erase()
    chosen = state.selected()
    if not chosen:
        _put(win, 1, 1, "Nothing selected. Press any key to go back.", attrs["header"])
        win.getch()
        return False
    _put(win, 1, 1, f"Move {len(chosen)} items ({format_size(state.selected_size())}) to the Trash?",
         attrs["header"])
    admin = [c for c in chosen if str(c.path).startswith("/Library/")]
    y = 3
    if admin:
        _put(win, y, 1, "Needs admin password:", attrs["dim"])
        y += 1
        for c in admin[: max(0, h - 7)]:
            _put(win, y, 3, str(c.path))
            y += 1
    _put(win, h - 1, 1, "y confirm · any other key back")
    win.refresh()
    return win.getch() in (ord("y"), ord("Y"))


def _loop(win, info: AppInfo, state: ChecklistState):
    import curses

    try:
        curses.curs_set(0)
    except curses.error:
        pass
    win.keypad(True)
    attrs = _colors()
    while True:
        _draw(win, info, state, attrs)
        k = win.getch()
        if k in (ord("q"), 27):
            return None
        if k in (curses.KEY_UP, ord("k")):
            state.move(-1)
        elif k in (curses.KEY_DOWN, ord("j")):
            state.move(1)
        elif k == curses.KEY_NPAGE:
            state.move(max(1, win.getmaxyx()[0] - 5))
        elif k == curses.KEY_PPAGE:
            state.move(-max(1, win.getmaxyx()[0] - 5))
        elif k == ord(" "):
            state.toggle()
        elif k == ord("a"):
            state.set_all(True)
        elif k == ord("n"):
            state.set_all(False)
        elif k in (curses.KEY_ENTER, 10, 13):
            if _confirm(win, state, attrs):
                return state.selected()
        # KEY_RESIZE and anything else: redraw on next loop.
