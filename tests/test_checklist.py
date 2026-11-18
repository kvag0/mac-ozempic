import unittest
from pathlib import Path

from ozempic.checklist import ChecklistState, truncate_middle
from ozempic.uninstaller import Candidate


def _items(groups=("g", "g", "g")):
    return [
        Candidate(Path(f"/x/{i}"), g, "name", checked, size)
        for i, (g, checked, size) in enumerate(zip(groups, (True, False, True), (100, 200, 300)))
    ]


class TestChecklistState(unittest.TestCase):
    def test_initial_selection(self):
        self.assertEqual(ChecklistState(_items()).selected_size(), 400)

    def test_toggle(self):
        s = ChecklistState(_items())
        s.move(1)
        s.toggle()
        self.assertEqual(s.selected_size(), 600)
        s.toggle()
        self.assertEqual(s.selected_size(), 400)

    def test_move_clamps(self):
        s = ChecklistState(_items())
        s.move(-5)
        self.assertEqual(s.cursor, 0)
        s.move(99)
        self.assertEqual(s.cursor, 2)

    def test_all_none(self):
        s = ChecklistState(_items())
        s.set_all(False)
        self.assertEqual(s.selected(), [])
        s.set_all(True)
        self.assertEqual(len(s.selected()), 3)

    def test_rows_insert_group_headers(self):
        s = ChecklistState(_items(("a", "a", "b")))
        self.assertEqual(s.rows, [("header", "a"), ("item", 0), ("item", 1),
                                  ("header", "b"), ("item", 2)])

    def test_scroll_follows_cursor(self):
        # rows: [header, i0, i1, i2]; height 2
        s = ChecklistState(_items())
        s.move(2)
        s.scroll(2)
        self.assertEqual(s.offset, 2)
        s.move(-2)
        s.scroll(2)
        self.assertEqual(s.offset, 0)  # header above first item stays visible

    def test_scroll_no_change_when_visible(self):
        s = ChecklistState(_items())
        s.scroll(10)
        s.move(2)
        s.scroll(10)
        self.assertEqual(s.offset, 0)


class TestTruncateMiddle(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(truncate_middle("abc", 5), "abc")

    def test_long_keeps_both_ends(self):
        out = truncate_middle("/Users/me/Library/Application Support/obsidian", 20)
        self.assertEqual(len(out), 20)
        self.assertTrue(out.startswith("/Users/me"))
        self.assertTrue(out.endswith("obsidian"))
        self.assertIn("…", out)


if __name__ == "__main__":
    unittest.main()
