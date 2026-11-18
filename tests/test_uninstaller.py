import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ozempic.uninstaller import (
    Roots,
    UninstallError,
    find_apps,
    read_app_info,
)


def make_app(parent: Path, name: str, bundle_id: str, helpers: dict | None = None) -> Path:
    """Create a fake .app bundle with Info.plist and optional embedded helper bundles."""
    app = parent / f"{name}.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleName": name}, f)
    for rel, helper_id in (helpers or {}).items():
        hc = contents / rel / "Contents"
        hc.mkdir(parents=True)
        with open(hc / "Info.plist", "wb") as f:
            plistlib.dump({"CFBundleIdentifier": helper_id}, f)
    return app


def make_roots(tmp: Path) -> Roots:
    roots = Roots(
        home=tmp / "home",
        system_library=tmp / "Library",
        app_dirs=[tmp / "Applications"],
        caskroom=tmp / "Caskroom",
    )
    for d in (roots.home, roots.system_library, roots.app_dirs[0], roots.caskroom):
        d.mkdir(parents=True, exist_ok=True)
    return roots


def fake_run(team: str = "TeamIdentifier=ABCDE12345\n", brew: dict | None = None, brew_missing: bool = False):
    brew = brew if brew is not None else {"casks": []}

    def run(args, **kwargs):
        if args[0] == "codesign":
            return subprocess.CompletedProcess(args, 0, "", team)
        if args[0] == "brew":
            if brew_missing:
                raise FileNotFoundError("brew")
            return subprocess.CompletedProcess(args, 0, json.dumps(brew), "")
        raise AssertionError(f"unexpected command {args}")

    return run


class TestFindApps(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.roots = make_roots(Path(self._tmp.name))
        self.apps = self.roots.app_dirs[0]
        self.obsidian = make_app(self.apps, "Obsidian", "md.obsidian")

    def tearDown(self):
        self._tmp.cleanup()

    def test_by_name_case_insensitive(self):
        self.assertEqual(find_apps("obsidian", self.roots), [self.obsidian])

    def test_one_level_subfolder(self):
        foo = make_app(self.apps / "Utilities", "Foo", "com.example.foo")
        self.assertEqual(find_apps("foo", self.roots), [foo])

    def test_by_bundle_id(self):
        self.assertEqual(find_apps("md.obsidian", self.roots), [self.obsidian])

    def test_by_path(self):
        self.assertEqual(find_apps(str(self.obsidian), self.roots), [self.obsidian])

    def test_no_match_returns_empty(self):
        self.assertEqual(find_apps("nope", self.roots), [])


class TestReadAppInfo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.roots = make_roots(Path(self._tmp.name))
        self.apps = self.roots.app_dirs[0]

    def tearDown(self):
        self._tmp.cleanup()

    def test_keys(self):
        app = make_app(self.apps, "Brave Browser", "com.brave.Browser",
                       helpers={"PlugIns/QL.appex": "com.brave.Browser.ql"})
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run()):
            info = read_app_info(app, self.roots)
        self.assertEqual(info.path, app)
        self.assertEqual(info.bundle_id, "com.brave.Browser")
        self.assertEqual(info.helper_ids, ["com.brave.Browser.ql"])
        self.assertIn("brave browser", info.names)
        self.assertIn("bravebrowser", info.names)
        self.assertEqual(info.vendor, "brave")
        self.assertEqual(info.team_id, "ABCDE12345")
        self.assertIsNone(info.cask)
        self.assertEqual(info.zap_paths, [])

    def test_vendor_under_4_chars_is_none(self):
        app = make_app(self.apps, "App", "io.ab.App")
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run()):
            info = read_app_info(app, self.roots)
        self.assertIsNone(info.vendor)

    def test_unsigned_team_is_none(self):
        app = make_app(self.apps, "Foo", "com.example.foo")
        with patch("ozempic.uninstaller.subprocess.run",
                   side_effect=fake_run(team="TeamIdentifier=not set\n")):
            info = read_app_info(app, self.roots)
        self.assertIsNone(info.team_id)

    def test_cask_zap_paths(self):
        app = make_app(self.apps, "Obsidian", "md.obsidian")
        home = self.roots.home
        (home / "Library/Application Support/obsidian").mkdir(parents=True)
        (home / "Library/Saved Application State/md.obsidian.savedState").mkdir(parents=True)
        brew = {"casks": [
            {"token": "other", "artifacts": [{"app": ["Other.app"]}]},
            {"token": "obsidian", "artifacts": [
                {"app": ["Obsidian.app"], "target": "/Applications/Obsidian.app"},
                {"zap": [{
                    "trash": [
                        "~/Library/Application Support/obsidian",
                        "~/Library/Saved Application State/md.obsidian.savedState",
                        "~/Library/Missing/*",
                    ],
                    "rmdir": "~/x",
                }]},
            ]},
        ]}
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run(brew=brew)):
            info = read_app_info(app, self.roots)
        self.assertEqual(info.cask, "obsidian")
        self.assertEqual(sorted(p.name for p in info.zap_paths),
                         ["md.obsidian.savedState", "obsidian"])

    def test_zap_single_string_delete(self):
        app = make_app(self.apps, "Foo", "com.example.foo")
        (self.roots.home / "Library/Caches").mkdir(parents=True)
        (self.roots.home / "Library/Caches/com.example.foo").touch()
        brew = {"casks": [{"token": "foo", "artifacts": [
            {"app": ["Foo.app"]},
            {"zap": [{"delete": "~/Library/Caches/com.example.foo"}]},
        ]}]}
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run(brew=brew)):
            info = read_app_info(app, self.roots)
        self.assertEqual([p.name for p in info.zap_paths], ["com.example.foo"])

    def test_brew_missing_means_no_cask(self):
        app = make_app(self.apps, "Foo", "com.example.foo")
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run(brew_missing=True)):
            info = read_app_info(app, self.roots)
        self.assertIsNone(info.cask)
        self.assertEqual(info.zap_paths, [])

    def test_apple_bundle_refused(self):
        app = make_app(self.apps, "Safari", "com.apple.Safari")
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run()):
            with self.assertRaises(UninstallError):
                read_app_info(app, self.roots)

    def test_system_applications_refused(self):
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run()):
            with self.assertRaises(UninstallError):
                read_app_info(Path("/System/Applications/Chess.app"), self.roots)

    def test_missing_info_plist_raises(self):
        bare = self.apps / "X.app"
        bare.mkdir()
        with patch("ozempic.uninstaller.subprocess.run", side_effect=fake_run()):
            with self.assertRaises(UninstallError):
                read_app_info(bare, self.roots)


if __name__ == "__main__":
    unittest.main()
