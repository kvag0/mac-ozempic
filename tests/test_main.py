import io
import json
import plistlib
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from ozempic import history
from ozempic.__main__ import main
from tests.test_uninstaller import fake_run, make_app, make_roots


class TestRouting(unittest.TestCase):
    def test_bare_runs_clean(self):
        with patch("ozempic.__main__.run_clean", return_value=0) as rc:
            self.assertEqual(main([]), 0)
        rc.assert_called_once_with(keep_logs=False, yes=False)

    def test_bare_flags_route_to_clean(self):
        with patch("ozempic.__main__.run_clean", return_value=0) as rc:
            main(["--keep-logs", "-y"])
        rc.assert_called_once_with(keep_logs=True, yes=True)

    def test_uninstall_routes(self):
        with patch("ozempic.__main__.run_uninstall", return_value=0) as ru:
            main(["uninstall", "Obsidian", "--dry-run"])
        ru.assert_called_once_with("Obsidian", True)


class _FlowBase(unittest.TestCase):
    """Fake roots + every system boundary patched; trash defaults to the happy path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.roots = make_roots(tmp)
        self.app = make_app(self.roots.app_dirs[0], "Obsidian", "md.obsidian")
        lib = self.roots.home / "Library"
        (lib / "Preferences").mkdir(parents=True)
        self.prefs = lib / "Preferences/md.obsidian.plist"
        self.prefs.write_bytes(b"x")
        (lib / "LaunchAgents").mkdir(parents=True)
        self.agent = lib / "LaunchAgents/md.obsidian.agent.plist"
        with open(self.agent, "wb") as f:
            plistlib.dump({"Label": "md.obsidian.agent"}, f)
        self.history = tmp / "history.log"

        self.trash = Mock()
        self.trash.finder_available.return_value = True
        self.trash.hosts_terminal.return_value = False
        self.trash.is_running.return_value = False
        self.trash.quit_app.return_value = True
        self.trash.move_to_trash.return_value = []

        self.stack = ExitStack()
        self.stack.enter_context(patch("ozempic.uninstaller.Roots.default", return_value=self.roots))
        self.stack.enter_context(patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run()))
        self.stack.enter_context(patch("ozempic.cleaner.check_fda", return_value=True))
        self.stack.enter_context(patch("ozempic.history.HISTORY_PATH", self.history))
        for name in ("finder_available", "hosts_terminal", "is_running", "quit_app",
                     "unload_launchd", "move_to_trash", "flush_prefs"):
            self.stack.enter_context(patch(f"ozempic.trash.{name}", getattr(self.trash, name)))
        self.checklist = self.stack.enter_context(patch("ozempic.__main__.run_checklist"))
        self.input = self.stack.enter_context(patch("builtins.input"))
        self.out = io.StringIO()
        self.stack.enter_context(redirect_stdout(self.out))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()


class TestUninstallFlow(_FlowBase):
    def test_dry_run_touches_nothing(self):
        self.assertEqual(main(["uninstall", "Obsidian", "--dry-run"]), 0)
        self.trash.move_to_trash.assert_not_called()
        self.checklist.assert_not_called()
        self.assertIn("md.obsidian.plist", self.out.getvalue())
        self.assertIn("bundle id", self.out.getvalue())

    def test_unknown_app_exit_1(self):
        self.assertEqual(main(["uninstall", "Nope"]), 1)
        self.trash.move_to_trash.assert_not_called()

    def test_apple_app_refused_exit_1(self):
        make_app(self.roots.app_dirs[0], "Safari", "com.apple.Safari")
        self.assertEqual(main(["uninstall", "Safari"]), 1)
        self.trash.move_to_trash.assert_not_called()

    def test_fda_missing_exit_1(self):
        with patch("ozempic.cleaner.check_fda", return_value=False):
            self.assertEqual(main(["uninstall", "Obsidian", "--dry-run"]), 1)

    def test_hosting_terminal_refused(self):
        self.trash.hosts_terminal.return_value = True
        self.assertEqual(main(["uninstall", "Obsidian"]), 1)
        self.trash.move_to_trash.assert_not_called()

    def test_finder_denied_aborts(self):
        self.trash.finder_available.return_value = False
        self.assertEqual(main(["uninstall", "Obsidian"]), 1)
        self.trash.move_to_trash.assert_not_called()
        self.checklist.assert_not_called()

    def test_quit_cancelled(self):
        self.trash.is_running.return_value = True
        self.input.return_value = "n"
        self.assertEqual(main(["uninstall", "Obsidian"]), 1)
        self.trash.quit_app.assert_not_called()
        self.trash.move_to_trash.assert_not_called()

    def test_quit_fails(self):
        self.trash.is_running.return_value = True
        self.trash.quit_app.return_value = False
        self.input.return_value = "y"
        self.assertEqual(main(["uninstall", "Obsidian"]), 1)
        self.trash.move_to_trash.assert_not_called()

    def test_checklist_quit_trashes_nothing(self):
        self.checklist.return_value = None
        self.assertEqual(main(["uninstall", "Obsidian"]), 0)
        self.trash.move_to_trash.assert_not_called()
        self.assertFalse(self.history.exists())

    def _selected(self, *paths):
        def pick(info, items):
            return [c for c in items if c.path in paths]
        self.checklist.side_effect = pick

    def test_full_run_order_and_history(self):
        self._selected(self.app, self.prefs, self.agent)
        self.assertEqual(main(["uninstall", "Obsidian"]), 0)
        order = [c[0] for c in self.trash.mock_calls
                 if c[0] in ("unload_launchd", "move_to_trash", "flush_prefs")]
        self.assertEqual(order, ["unload_launchd", "move_to_trash", "flush_prefs"])
        self.assertEqual(self.trash.unload_launchd.call_args.args[0], [self.agent])
        self.assertEqual(sorted(self.trash.move_to_trash.call_args.args[0]),
                         sorted([self.app, self.prefs, self.agent]))
        lines = self.history.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["subcommand"], "uninstall")
        self.assertEqual(entry["bundle_id"], "md.obsidian")
        self.assertEqual(len(entry["removed"]), 3)
        self.assertEqual(entry["failed"], [])
        self.assertIn("UNINSTALLED", self.out.getvalue())

    def test_failures_reported_and_exit_1(self):
        self._selected(self.app, self.prefs)
        self.trash.move_to_trash.return_value = [(self.prefs, "denied")]
        self.assertEqual(main(["uninstall", "Obsidian"]), 1)
        entry = json.loads(self.history.read_text())
        self.assertEqual(entry["failed"], [{"path": str(self.prefs), "reason": "denied"}])
        self.assertEqual(len(entry["removed"]), 1)
        self.trash.flush_prefs.assert_not_called()  # the plist did not actually go
        self.assertIn("NOT REMOVED", self.out.getvalue())

    def test_no_prefs_no_flush(self):
        self._selected(self.app)
        main(["uninstall", "Obsidian"])
        self.trash.flush_prefs.assert_not_called()
        self.trash.unload_launchd.assert_not_called()

    def test_ambiguous_app_prompts(self):
        second = make_app(self.roots.app_dirs[0] / "Utilities", "Obsidian", "md.obsidian.beta")
        self.input.return_value = "2"
        self.assertEqual(main(["uninstall", "Obsidian", "--dry-run"]), 0)
        self.assertIn(str(second), self.out.getvalue())

    def test_ambiguous_invalid_choice_exit_1(self):
        make_app(self.roots.app_dirs[0] / "Utilities", "Obsidian", "md.obsidian.beta")
        self.input.return_value = "9"
        self.assertEqual(main(["uninstall", "Obsidian", "--dry-run"]), 1)


class TestCleanHistory(_FlowBase):
    def test_clean_writes_history(self):
        result = [{"label": "User caches", "size_str": "1 MB", "action": None}]
        with patch("ozempic.cleaner.clean_all", return_value=result), \
             patch("ozempic.cleaner.get_review_items", return_value=[]):
            self.assertEqual(main(["clean", "-y"]), 0)
        entry = json.loads(self.history.read_text())
        self.assertEqual(entry["subcommand"], "clean")
        self.assertEqual(entry["results"], result)


class TestHistory(unittest.TestCase):
    def test_append_writes_json_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub/history.log"
            history.append({"a": 1}, path)
            history.append({"b": 2}, path)
            lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("ts", json.loads(line))
        self.assertEqual(json.loads(lines[1])["b"], 2)

    def test_append_oserror_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            err = io.StringIO()
            with patch("sys.stderr", err):
                history.append({"a": 1}, blocker / "history.log")
        self.assertIn("history", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
