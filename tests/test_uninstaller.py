import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ozempic.uninstaller import (
    AppInfo,
    OtherApps,
    Roots,
    UninstallError,
    find_apps,
    find_candidates,
    other_apps,
    read_app_info,
    strip_group_prefix,
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


class TestStripGroupPrefix(unittest.TestCase):
    def test_real_names_from_this_mac(self):
        cases = {
            "SY64MV22J9.com.raycast.macos.shared": ("com.raycast.macos.shared", "SY64MV22J9"),
            "group.W5364U7YZB.io.tailscale.shared": ("io.tailscale.shared", "W5364U7YZB"),
            "group.com.docker": ("com.docker", None),
            "group.net.whatsapp.family": ("net.whatsapp.family", None),
            "RP2S87B72W.eu.exelban.Stats.widgets": ("eu.exelban.Stats.widgets", "RP2S87B72W"),
        }
        for raw, expected in cases.items():
            self.assertEqual(strip_group_prefix(raw), expected, raw)


class TestFindCandidates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.roots = make_roots(Path(self._tmp.name))
        self.apps = self.roots.app_dirs[0]
        self.app = make_app(self.apps, "Obsidian", "md.obsidian")
        self.info = self._info(self.app, "md.obsidian", ["md.obsidian.quicklook"], ["obsidian"])
        self.others = OtherApps(ids=set(), names=set(), paths=[])

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _info(app, bundle_id, helpers, names, team="6JSW4SJWN9", vendor=None, cask=None, zap=None):
        if vendor is None:
            parts = bundle_id.lower().split(".")
            vendor = parts[1] if len(parts) > 1 and len(parts[1]) >= 4 else None
        return AppInfo(path=app, bundle_id=bundle_id, helper_ids=helpers, names=names,
                       vendor=vendor, team_id=team, cask=cask, zap_paths=zap or [])

    def user(self, rel: str, is_dir: bool = True) -> Path:
        p = self.roots.home / "Library" / rel
        if is_dir:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        return p

    def system(self, rel: str) -> Path:
        p = self.roots.system_library / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def results(self, info=None, others=None):
        with patch("ozempic.uninstaller.subprocess.run",
                   side_effect=fake_run(team="TeamIdentifier=6JSW4SJWN9\n")):
            return find_candidates(info or self.info, others or self.others, self.roots)

    def state(self, path: Path, info=None, others=None):
        for c in self.results(info, others):
            if c.path == path:
                return (c.reason, c.checked)
        return None

    def test_app_itself(self):
        self.assertEqual(self.state(self.app), ("app", True))

    def test_app_group_is_application(self):
        c = [c for c in self.results() if c.path == self.app][0]
        self.assertEqual(c.group, "Application")

    def test_bundle_id_plist(self):
        p = self.user("Preferences/md.obsidian.plist", is_dir=False)
        self.assertEqual(self.state(p), ("bundle id", True))

    def test_byhost_plist(self):
        p = self.user("Preferences/ByHost/md.obsidian.1234-ABCD.plist", is_dir=False)
        self.assertEqual(self.state(p), ("bundle id", True))

    def test_helper_container(self):
        p = self.user("Containers/md.obsidian.quicklook")
        self.assertEqual(self.state(p), ("helper", True))

    def test_group_container_team_prefixed_bundle(self):
        p = self.user("Group Containers/6JSW4SJWN9.md.obsidian.shared")
        self.assertEqual(self.state(p), ("bundle id", True))

    def test_group_container_vendor_only(self):
        app = make_app(self.apps, "WhatsApp", "net.whatsapp.WhatsApp")
        info = self._info(app, "net.whatsapp.WhatsApp", [], ["whatsapp"], team="57T9237FN3")
        fam = self.user("Group Containers/group.net.whatsapp.family")
        shared = self.user("Group Containers/group.net.whatsapp.WhatsApp.shared")
        self.assertEqual(self.state(fam, info), ("vendor (shared)", False))
        self.assertEqual(self.state(shared, info), ("bundle id", True))

    def test_group_container_team_only_unique(self):
        p = self.user("Group Containers/6JSW4SJWN9.something")
        self.assertEqual(self.state(p), ("team", True))

    def test_group_container_team_only_shared(self):
        other = make_app(self.apps, "Canvas", "md.canvas")
        others = OtherApps(ids={"md.canvas"}, names={"canvas"}, paths=[other])
        p = self.user("Group Containers/6JSW4SJWN9.something")
        self.assertEqual(self.state(p, others=others), ("team (shared)", False))

    def test_launchd_by_program_path(self):
        p = self.user("LaunchAgents/x.y.plist", is_dir=False)
        with open(p, "wb") as f:
            plistlib.dump({"Label": "x.y",
                           "ProgramArguments": [str(self.app) + "/Contents/MacOS/obsidian"]}, f)
        self.assertEqual(self.state(p), ("launchd", True))

    def test_system_launch_daemon_by_label(self):
        p = self.system("LaunchDaemons/md.obsidian.helper.plist")
        c = [c for c in self.results() if c.path == p][0]
        self.assertEqual((c.reason, c.checked, c.group),
                         ("bundle id", True, "/Library/LaunchDaemons"))

    def test_corrupt_launchd_plist_skipped(self):
        p = self.user("LaunchAgents/z.z.plist", is_dir=False)
        p.write_bytes(b"\x00garbage")
        self.assertIsNone(self.state(p))

    def test_exact_name_app_support(self):
        p = self.user("Application Support/obsidian")
        self.assertEqual(self.state(p), ("name", True))

    def test_name_ambiguous_when_other_app_shares(self):
        others = OtherApps(ids=set(), names={"obsidian"}, paths=[])
        p = self.user("Application Support/obsidian")
        self.assertEqual(self.state(p, others=others), ("name (ambiguous)", False))

    def test_name_under_4_chars_ambiguous(self):
        app = make_app(self.apps, "Arc", "company.thebrowser.Browser")
        info = self._info(app, "company.thebrowser.Browser", [], ["arc"])
        p = self.user("Application Support/Arc")
        self.assertEqual(self.state(p, info), ("name (ambiguous)", False))

    def test_partial_vendor(self):
        app = make_app(self.apps, "Brave Browser", "com.brave.Browser")
        info = self._info(app, "com.brave.Browser", [], ["brave browser", "bravebrowser"])
        p = self.user("Application Support/BraveSoftware")
        self.assertEqual(self.state(p, info), ("partial", False))

    def test_crash_report(self):
        p = self.user("Logs/DiagnosticReports/Obsidian-2026-10-01-120000.ips", is_dir=False)
        self.assertEqual(self.state(p), ("crash report", True))

    def test_crash_report_needs_delimiter(self):
        p = self.user("Logs/DiagnosticReports/ObsidianX-2026.ips", is_dir=False)
        self.assertNotEqual(self.state(p)[0], "crash report")

    def test_brew_zap_beats_other_rules(self):
        p = self.user("Application Support/obsidian")
        info = self._info(self.app, "md.obsidian", [], ["obsidian"], zap=[p])
        matches = [c for c in self.results(info) if c.path == p]
        self.assertEqual(len(matches), 1)
        self.assertEqual((matches[0].reason, matches[0].checked), ("brew zap", True))

    def test_zap_equal_to_location_root_skipped(self):
        root = self.user("Caches")
        info = self._info(self.app, "md.obsidian", [], ["obsidian"], zap=[root])
        self.assertIsNone(self.state(root, info))

    def test_caskroom_entry(self):
        cr = self.roots.caskroom / "obsidian"
        cr.mkdir()
        info = self._info(self.app, "md.obsidian", [], ["obsidian"], cask="obsidian")
        c = [c for c in self.results(info) if c.path == cr][0]
        self.assertEqual((c.reason, c.checked, c.group), ("cask", True, "Homebrew"))

    def test_com_apple_excluded(self):
        p = self.user("Caches/com.apple.obsidian.thing")
        self.assertIsNone(self.state(p))

    def test_longer_other_app_id_excluded(self):
        app = make_app(self.apps, "FooApp", "com.foo.app")
        info = self._info(app, "com.foo.app", [], ["fooapp"])
        others = OtherApps(ids={"com.foo.app.pro"}, names=set(), paths=[])
        pro = self.user("Preferences/com.foo.app.pro.plist", is_dir=False)
        own = self.user("Preferences/com.foo.app.plist", is_dir=False)
        self.assertIsNone(self.state(pro, info, others))
        self.assertEqual(self.state(own, info, others), ("bundle id", True))

    def test_unreadable_location_skipped(self):
        self.user("Containers/md.obsidian.quicklook")
        prefs = self.user("Preferences/md.obsidian.plist", is_dir=False)
        real_iterdir = Path.iterdir

        def iterdir(path):
            if path.name == "Containers":
                raise PermissionError("denied")
            return real_iterdir(path)

        with patch.object(Path, "iterdir", iterdir):
            self.assertEqual(self.state(prefs), ("bundle id", True))

    def test_only_direct_children(self):
        p = self.user("Caches/sub/md.obsidian")
        self.assertIsNone(self.state(p))

    def test_sizes_reported(self):
        p = self.user("Preferences/md.obsidian.plist", is_dir=False)
        c = [c for c in self.results() if c.path == p][0]
        self.assertEqual(c.size, 1)


class TestOtherApps(unittest.TestCase):
    def test_collects_ids_and_names_excluding_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = make_roots(Path(tmp))
            target = make_app(roots.app_dirs[0], "Obsidian", "md.obsidian")
            make_app(roots.app_dirs[0], "Stats", "eu.exelban.Stats",
                     helpers={"PlugIns/W.appex": "eu.exelban.Stats.widgets"})
            others = other_apps(roots, exclude=target)
        self.assertEqual(others.ids, {"eu.exelban.stats", "eu.exelban.stats.widgets"})
        self.assertIn("stats", others.names)
        self.assertNotIn("obsidian", others.names)
        self.assertEqual([p.name for p in others.paths], ["Stats.app"])


if __name__ == "__main__":
    unittest.main()
