import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCleanElectronSubCaches(unittest.TestCase):
    def test_permission_error_on_iterdir_is_skipped(self):
        """PermissionError on app_dir.iterdir() must not crash the function."""
        from ozempic.cleaner import _clean_electron_sub_caches

        mock_app_dir = MagicMock(spec=Path)
        mock_app_dir.is_dir.return_value = True
        mock_app_dir.name = "SomeApp"
        mock_app_dir.__str__ = lambda s: "/fake/Library/Application Support/SomeApp"
        mock_app_dir.iterdir.side_effect = PermissionError("access denied")

        mock_base = MagicMock(spec=Path)
        mock_base.is_dir.return_value = True
        mock_base.iterdir.return_value = iter([mock_app_dir])

        with patch("ozempic.cleaner.Path") as MockPath:
            MockPath.return_value.expanduser.return_value = mock_base
            result = _clean_electron_sub_caches()

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
