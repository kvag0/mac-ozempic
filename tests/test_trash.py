import getpass
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ozempic import trash
from ozempic.uninstaller import AppInfo


def _info(bundle_id="md.obsidian", helpers=None, path="/Applications/Obsidian.app"):
    return AppInfo(path=Path(path), bundle_id=bundle_id, helper_ids=helpers or [],
                   names=["obsidian"], vendor="obsidian", team_id=None, cask=None, zap_paths=[])


def _done(rc=0, stdout="", stderr=""):
    return lambda args, **kw: subprocess.CompletedProcess(args, rc, stdout, stderr)


class TestTrash(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_finder_available_true_on_rc0(self):
        with patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            self.assertTrue(trash.finder_available())
        self.assertEqual(run.call_args.args[0][0], "osascript")

    def test_finder_available_false_on_rc1(self):
        with patch("ozempic.trash.subprocess.run", side_effect=_done(1)):
            self.assertFalse(trash.finder_available())

    def test_hosts_terminal(self):
        with patch.dict(os.environ, {"__CFBundleIdentifier": "org.alacritty"}):
            self.assertTrue(trash.hosts_terminal(_info("org.alacritty")))
            self.assertTrue(trash.hosts_terminal(_info("org.Alacritty")))
            self.assertFalse(trash.hosts_terminal(_info("md.obsidian")))

    def test_hosts_terminal_via_helper(self):
        with patch.dict(os.environ, {"__CFBundleIdentifier": "com.foo.term.helper"}):
            self.assertTrue(trash.hosts_terminal(_info("com.foo.term", ["com.foo.term.helper"])))

    def test_is_running_matches_bundle_path_literally(self):
        info = _info(path="/Applications/Foo (Beta).app")
        ps = "/usr/sbin/cfprefsd agent\n/Applications/Foo (Beta).app/Contents/MacOS/Foo -psn\n"
        with patch("ozempic.trash.subprocess.run", side_effect=_done(0, stdout=ps)):
            self.assertTrue(trash.is_running(info))
        with patch("ozempic.trash.subprocess.run",
                   side_effect=_done(0, stdout="/Applications/Foo Beta.app/Contents/MacOS/Foo\n")):
            self.assertFalse(trash.is_running(info))

    def test_quit_app_rejects_unsafe_bundle_id(self):
        with patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            self.assertFalse(trash.quit_app(_info('x" & do shell script "rm')))
        run.assert_not_called()

    def test_quit_app_returns_true_once_stopped(self):
        calls = []

        def run(args, **kw):
            calls.append(args)
            # osascript quit -> 0; pgrep -> not running (1)
            return subprocess.CompletedProcess(args, 0 if args[0] == "osascript" else 1, "", "")

        with patch("ozempic.trash.subprocess.run", side_effect=run):
            self.assertTrue(trash.quit_app(_info(), timeout=1.0))
        self.assertIn('quit app id "md.obsidian"', " ".join(calls[0]))

    def test_move_to_trash_passes_paths_as_argv(self):
        p = self.tmp / "Bob's \"Tool\" ü.app"
        p.mkdir()

        def run(args, **kw):
            shutil.rmtree(p)
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch("ozempic.trash.subprocess.run", side_effect=run) as m:
            failures = trash.move_to_trash([p])
        args = m.call_args.args[0]
        self.assertEqual(args[0], "osascript")
        self.assertEqual(args[-1], str(p))
        self.assertNotIn(str(p), " ".join(args[:args.index("--")]))
        self.assertEqual(failures, [])

    def test_move_to_trash_reports_survivors(self):
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir()
        b.mkdir()

        def run(args, **kw):
            a.rmdir()
            return subprocess.CompletedProcess(args, 1, "", "Finder got an error: denied.\n")

        with patch("ozempic.trash.subprocess.run", side_effect=run):
            failures = trash.move_to_trash([a, b])
        self.assertEqual(failures, [(b, "Finder got an error: denied.")])

    def test_move_to_trash_empty_list_no_call(self):
        with patch("ozempic.trash.subprocess.run") as run:
            self.assertEqual(trash.move_to_trash([]), [])
        run.assert_not_called()

    def _plist(self, path: Path, label: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump({"Label": label}, f)
        return path

    def test_unload_user_agent(self):
        p = self._plist(self.tmp / "Library/LaunchAgents/a.b.plist", "a.b")
        with patch("ozempic.trash.Path.home", return_value=self.tmp), \
             patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            trash.unload_launchd([p])
        self.assertEqual(run.call_args.args[0],
                         ["launchctl", "bootout", f"gui/{os.getuid()}/a.b"])

    def test_unload_system_daemon_uses_admin_osascript(self):
        home = self.tmp / "home"
        d1 = self._plist(self.tmp / "sys/LaunchDaemons/x.plist", "com.x.helper")
        d2 = self._plist(self.tmp / "sys/LaunchDaemons/y.plist", "com.y.helper")
        with patch("ozempic.trash.Path.home", return_value=home), \
             patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            trash.unload_launchd([d1, d2])
        self.assertEqual(run.call_count, 1)
        script = " ".join(run.call_args.args[0])
        self.assertIn("launchctl bootout system/com.x.helper", script)
        self.assertIn("launchctl bootout system/com.y.helper", script)
        self.assertIn("with administrator privileges", script)

    def test_unload_skips_unsafe_and_unreadable_labels(self):
        home = self.tmp / "home"
        bad = self._plist(self.tmp / "sys/LaunchDaemons/bad.plist", 'x"; rm -rf /; "')
        junk = self.tmp / "sys/LaunchDaemons/junk.plist"
        junk.write_bytes(b"\x00nope")
        with patch("ozempic.trash.Path.home", return_value=home), \
             patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            trash.unload_launchd([bad, junk])
        run.assert_not_called()

    def test_unload_truncated_xml_skipped(self):
        p = self.tmp / "sys/LaunchDaemons/t.plist"
        p.parent.mkdir(parents=True)
        p.write_bytes(b'<?xml version="1.0"?><plist><dict><key>Label</key>')
        with patch("ozempic.trash.Path.home", return_value=self.tmp / "home"), \
             patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            trash.unload_launchd([p])
        run.assert_not_called()

    def test_symlink_moved_to_trash_not_its_target(self):
        home = self.tmp / "home"
        (home / ".Trash").mkdir(parents=True)
        target = self.tmp / "dotfiles/real.plist"
        target.parent.mkdir()
        target.write_text("keep me")
        (home / ".Trash/x.plist").write_text("older item with same name")
        link = self.tmp / "LaunchAgents/x.plist"
        link.parent.mkdir()
        link.symlink_to(target)
        with patch("ozempic.trash.Path.home", return_value=home), \
             patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            failures = trash.move_to_trash([link])
        self.assertEqual(failures, [])
        run.assert_not_called()
        self.assertFalse(link.is_symlink())
        self.assertEqual(target.read_text(), "keep me")
        moved = [p for p in (home / ".Trash").iterdir() if p.is_symlink()]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].resolve(), target.resolve())

    def test_flush_prefs(self):
        with patch("ozempic.trash.subprocess.run", side_effect=_done(0)) as run:
            trash.flush_prefs()
        self.assertEqual(run.call_args.args[0], ["killall", "-u", getpass.getuser(), "cfprefsd"])


if __name__ == "__main__":
    unittest.main()
