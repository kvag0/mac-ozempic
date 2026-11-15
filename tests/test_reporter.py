import unittest
from ozempic.reporter import _calculate_total_size, _visible_len


class TestCalculateTotalSize(unittest.TestCase):
    def test_size_only(self):
        results = [
            {"size_str": "1.2 GB"},
            {"size_str": "300 MB"},
        ]
        total = _calculate_total_size(results)
        self.assertIn("GB", total)
        self.assertNotIn("files", total)

    def test_files_only(self):
        results = [{"size_str": "42 files"}]
        total = _calculate_total_size(results)
        self.assertEqual(total, "42 files")

    def test_size_and_files_combined(self):
        results = [
            {"size_str": "1.8 GB"},
            {"size_str": "42 files"},
        ]
        total = _calculate_total_size(results)
        self.assertIn("GB", total)
        self.assertIn("42 files", total)
        self.assertIn(" and ", total)

    def test_empty(self):
        self.assertEqual(_calculate_total_size([]), "0 B")


class TestVisibleLen(unittest.TestCase):
    def test_standard_text(self):
        self.assertEqual(_visible_len("hello"), 5)

    def test_ansi_escape_sequences(self):
        colored = "\033[92mhello\033[0m"
        self.assertEqual(_visible_len(colored), 5)

    def test_double_width_emojis(self):
        # "📂" is double width (2 columns)
        self.assertEqual(_visible_len("📂 caches"), 9)  # 2 for emoji, 7 for " caches"

    def test_mixed(self):
        # "\033[92m📂\033[0m" has visible length of 2
        self.assertEqual(_visible_len("\033[92m📂\033[0m caches"), 9)


if __name__ == "__main__":
    unittest.main()
