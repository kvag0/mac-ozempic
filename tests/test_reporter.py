import unittest
from ozempic.reporter import _calculate_total_size


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


if __name__ == "__main__":
    unittest.main()
