# ozempic uninstall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ozempic uninstall <App>`: AppCleaner-depth leftover discovery, a curses checklist, and Trash-only removal via Finder; split the CLI into `clean`/`uninstall` subcommands and add a history log.

**Architecture:** Discovery and matching are pure functions over injectable filesystem roots (`uninstaller.py`). Side effects (Finder, launchctl, osascript, cfprefsd) live in `trash.py`. The curses UI wraps a pure `ChecklistState` (`checklist.py`). `__main__.py` orchestrates; `history.py` appends JSON lines.

**Tech Stack:** Python ≥3.10 stdlib only (`curses`, `plistlib`, `subprocess`, `pathlib`, `dataclasses`, `json`), `unittest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-11-18-uninstall-design.md`

## Global Constraints

- Stdlib only. No new dependencies.
- `requires-python = ">=3.10"` in `pyproject.toml`.
- `uninstall` never calls `rm`, `unlink`, `shutil.rmtree` on candidates. Trash via Finder only; if Finder fails, report and stop. No fallback.
- Refuse apps under `/System/Applications` and bundle IDs starting `com.apple.`.
- History log path: `~/Library/Application Support/ozempic/history.log` (never `~/Library/Logs`).
- Branding unchanged: `reporter.print_logo()`, card style (`reporter._print_card`), icons, `Spinner`.
- All name comparisons are case-insensitive (lowercase both sides).
- Tests: `unittest`; run from repo root with `python3 -m unittest discover -q`. No test touches the real system: every `subprocess.run` is patched.
- Do not use `git stash`. `git add` by path.

## Review Focus

1. **Another installed app owns a longer matching ID** (target `com.foo.app`, other app `com.foo.app.pro`, entry `com.foo.app.pro.plist`): the entry must be excluded, not checked. Test in Task 2.
2. **Paths containing quotes, spaces, or non-ASCII** (`/Applications/Bob's "Tool".app`): Finder must receive them intact. Paths go to `osascript` as argv, never interpolated into script text. Test in Task 3.
3. **Finder succeeds for some paths and fails for others**: report exactly the paths that still exist afterwards as failures; never claim everything was removed. Test in Task 3.
4. **App name that is generic or shared** ("Notes", "Stats" vs `Stats Widgets`, names < 4 chars): exact-name rows must start unchecked when ambiguous. Test in Task 2.
5. **Unreadable entries** (PermissionError on `iterdir`, a `LaunchAgents` plist that is binary-corrupt, an app with no `Info.plist`): skip the entry, never crash the scan. Test in Task 2 (corrupt plist) and Task 1 (missing Info.plist raises a clean `UninstallError`).

---

### Task 1: App discovery and AppInfo

**Files:**
- Create: `ozempic/uninstaller.py`
- Create: `tests/test_uninstaller.py`
- Modify: `pyproject.toml` (`requires-python = ">=3.10"`)

**Interfaces:**
- Produces (in `ozempic/uninstaller.py`):
  - `class UninstallError(Exception)`
  - `@dataclass class Roots: home: Path; system_library: Path; app_dirs: list[Path]; caskroom: Path` with classmethod `Roots.default() -> Roots` = `Path.home()`, `Path("/Library")`, `[Path("/Applications"), Path.home()/"Applications"]`, `Path("/opt/homebrew/Caskroom")`.
  - `@dataclass class AppInfo: path: Path; bundle_id: str; helper_ids: list[str]; names: list[str]; vendor: str | None; team_id: str | None; cask: str | None; zap_paths: list[Path]`
  - `find_apps(query: str, roots: Roots) -> list[Path]`
  - `read_app_info(app: Path, roots: Roots) -> AppInfo`
  - Test helper in `tests/test_uninstaller.py`: `make_app(parent: Path, name: str, bundle_id: str, helpers: dict[str, str] | None = None) -> Path` (helpers maps relative path inside `Contents/` like `"PlugIns/QL.appex"` to that bundle's ID; writes `Info.plist` with `plistlib`).

- [ ] **Step 1: Write the failing tests** in `tests/test_uninstaller.py`

```python
class TestFindApps(unittest.TestCase):
    # tmp Roots: app_dirs=[tmp/Applications], Utilities subfolder supported
    def test_by_name_case_insensitive(self):       # "obsidian" -> [.../Obsidian.app]
    def test_one_level_subfolder(self):           # Applications/Utilities/Foo.app found by "foo"
    def test_by_bundle_id(self):                  # "md.obsidian" -> [.../Obsidian.app]
    def test_by_path(self):                       # str(path to .app) -> [that path]
    def test_no_match_returns_empty(self):

class TestReadAppInfo(unittest.TestCase):
    def test_keys(self):
        # make_app(apps, "Brave Browser", "com.brave.Browser",
        #          helpers={"PlugIns/QL.appex": "com.brave.Browser.ql"})
        # codesign mocked -> stderr "TeamIdentifier=ABCDE12345\n"; brew mocked -> {"casks": []}
        info = read_app_info(app, roots)
        self.assertEqual(info.bundle_id, "com.brave.Browser")
        self.assertEqual(info.helper_ids, ["com.brave.Browser.ql"])
        self.assertIn("brave browser", info.names)
        self.assertIn("bravebrowser", info.names)
        self.assertEqual(info.vendor, "brave")
        self.assertEqual(info.team_id, "ABCDE12345")
        self.assertIsNone(info.cask)
    def test_vendor_under_4_chars_is_none(self):   # "io.ab.App" -> vendor None
    def test_unsigned_team_is_none(self):          # codesign stderr "TeamIdentifier=not set" -> None
    def test_cask_zap_paths(self):
        # brew stdout: {"casks":[{"token":"obsidian","artifacts":[
        #   {"app":["Obsidian.app"],"target":"/Applications/Obsidian.app"},
        #   {"zap":[{"trash":["~/Library/Application Support/obsidian",
        #                     "~/Library/Saved Application State/md.obsidian.savedState",
        #                     "~/Library/Missing/*"], "rmdir":"~/x"}]}]}]}
        # with tmp home containing the first two paths only
        self.assertEqual(info.cask, "obsidian")
        self.assertEqual(sorted(p.name for p in info.zap_paths),
                         ["md.obsidian.savedState", "obsidian"])
    def test_brew_missing_means_no_cask(self):     # subprocess.run raises FileNotFoundError -> cask None
    def test_apple_bundle_refused(self):           # "com.apple.Safari" -> raises UninstallError
    def test_system_applications_refused(self):    # path under "/System/Applications" -> UninstallError
    def test_missing_info_plist_raises(self):      # bare dir "X.app" -> UninstallError
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_uninstaller -v`
Expected: FAIL / ImportError on `ozempic.uninstaller`.

- [ ] **Step 3: Implement in `ozempic/uninstaller.py`**

- `find_apps`: glob `*.app` and `*/*.app` in each `app_dirs` entry; match query against `.app` stem (lowercased) or `CFBundleIdentifier`; a query that is an existing path ending `.app` returns `[Path(query)]`.
- `read_app_info`:
  - Read `Contents/Info.plist` with `plistlib`, raise `UninstallError` if it's missing.
  - Helper IDs: the `CFBundleIdentifier` of every `*/Contents/Info.plist` (or `Info.plist`) bundle under `Contents/{Library/LoginItems,Library/LaunchServices,XPCServices,PlugIns,Frameworks,Helpers}`, depth 1 (plus `Frameworks/*.app`). Dedupe, exclude the main ID.
  - `names`: `CFBundleName`, `CFBundleDisplayName`, `.app` stem, each lowercased, plus a spaces-removed variant. Dedupe.
  - `vendor`: second dot-component, lowercased, `None` if under 4 chars.
  - Team ID: `subprocess.run(["codesign","-dv","--verbose=2",str(app)], capture_output=True, text=True)`, parse `TeamIdentifier=(\S+)` from stderr, `"not set"` gives `None`.
  - Cask: `subprocess.run(["brew","info","--cask","--json=v2","--installed"], ...)`; the cask whose `app` artifact lists a string or `target` with basename == `app.name`. Zap: for each `zap` artifact entry, take the `trash` and `delete` values (str or list), expand a leading `~` to `roots.home`, `glob`, keep existing. `FileNotFoundError` or nonzero return means no cask.
- `pyproject.toml`: `requires-python = ">=3.10"`.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_uninstaller -v`
Expected: all PASS; then `python3 -m unittest discover -q` → OK (16 old + new).

- [ ] **Step 5: Commit**

```bash
git add ozempic/uninstaller.py tests/test_uninstaller.py pyproject.toml
git commit -m "feat(uninstall): app discovery and AppInfo extraction"
```

---

### Task 2: Leftover matcher

**Files:**
- Modify: `ozempic/uninstaller.py`
- Modify: `tests/test_uninstaller.py`

**Interfaces:**
- Consumes: `Roots`, `AppInfo`, `read_app_info`, `make_app` (Task 1).
- Produces:
  - `@dataclass class Candidate: path: Path; group: str; reason: str; checked: bool; size: int`
    - `group`: display header: `"Application"`, `"Homebrew"`, or the location shown with `~` for home (e.g. `"~/Library/Containers"`, `"/Library/LaunchDaemons"`).
    - `reason` values (exact strings): `"app"`, `"cask"`, `"brew zap"`, `"bundle id"`, `"helper"`, `"launchd"`, `"name"`, `"name (ambiguous)"`, `"team"`, `"team (shared)"`, `"vendor (shared)"`, `"partial"`, `"crash report"`.
  - `@dataclass class OtherApps: ids: set[str]; names: set[str]; paths: list[Path]` (lowercased IDs incl. helpers; names as in `AppInfo.names`)
  - `other_apps(roots: Roots, exclude: Path) -> OtherApps`
  - `strip_group_prefix(name: str) -> tuple[str, str | None]` returns `(rest, team_id_or_None)`
  - `find_candidates(info: AppInfo, others: OtherApps, roots: Roots) -> list[Candidate]`: sorted by group in the spec's location order, then path; one entry per path.

- [ ] **Step 1: Write the failing tests**

```python
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
            self.assertEqual(strip_group_prefix(raw), expected)

class TestFindCandidates(unittest.TestCase):
    # setUp: tmp home + tmp system_library with the spec's location dirs; target app
    # "Obsidian" md.obsidian, helper md.obsidian.quicklook, team 6JSW4SJWN9;
    # helper: state(path) -> (reason, checked) from find_candidates result
    def test_app_itself(self):                 # ("app", True)
    def test_bundle_id_plist(self):            # Preferences/md.obsidian.plist -> ("bundle id", True)
    def test_byhost_plist(self):               # Preferences/ByHost/md.obsidian.1234-ABCD.plist -> ("bundle id", True)
    def test_helper_container(self):           # Containers/md.obsidian.quicklook -> ("helper", True)
    def test_group_container_team_prefixed_bundle(self):  # 6JSW4SJWN9.md.obsidian.shared -> ("bundle id", True)
    def test_group_container_vendor_only(self):           # target net.whatsapp.WhatsApp: group.net.whatsapp.family -> ("vendor (shared)", False)
    def test_group_container_team_only_unique(self):      # 6JSW4SJWN9.something -> ("team", True)
    def test_group_container_team_only_shared(self):      # other app with same team (codesign mocked) -> ("team (shared)", False)
    def test_launchd_by_program_path(self):    # LaunchAgents/x.y.plist {"Label":"x.y","ProgramArguments":[str(app)+"/Contents/MacOS/obsidian"]} -> ("launchd", True)
    def test_corrupt_launchd_plist_skipped(self):  # b"\x00garbage" -> not in result, no exception
    def test_exact_name_app_support(self):     # Application Support/obsidian -> ("name", True)
    def test_name_ambiguous_when_other_app_shares(self):  # others.names has "obsidian" -> ("name (ambiguous)", False)
    def test_name_under_4_chars_ambiguous(self):          # app named "Arc": Application Support/Arc -> ("name (ambiguous)", False)
    def test_partial_vendor(self):             # target com.brave.Browser: Application Support/BraveSoftware -> ("partial", False)
    def test_crash_report(self):               # Logs/DiagnosticReports/Obsidian-2026-10-01-120000.ips -> ("crash report", True)
    def test_crash_report_needs_delimiter(self):  # ObsidianX-2026.ips -> not "crash report"
    def test_brew_zap_beats_other_rules(self):    # zap path also matching name -> ("brew zap", True), appears once
    def test_caskroom_entry(self):             # info.cask="obsidian", caskroom/obsidian exists -> ("cask", True), group "Homebrew"
    def test_com_apple_excluded(self):         # Caches/com.apple.obsidian.thing -> absent
    def test_longer_other_app_id_excluded(self):  # target com.foo.app, others.ids {"com.foo.app.pro"}: Preferences/com.foo.app.pro.plist -> absent; com.foo.app.plist -> ("bundle id", True)
    def test_unreadable_location_skipped(self):   # patch Path.iterdir to raise PermissionError for Containers -> other rows still returned
    def test_only_direct_children(self):       # Caches/sub/md.obsidian -> absent
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_uninstaller -v`
Expected: new tests FAIL (ImportError on `Candidate`/`find_candidates`).

- [ ] **Step 3: Implement**

- Location list (user = `roots.home/"Library"/x`, system = `roots.system_library/x`), in display order:
  user: `Application Support, Caches, Preferences, Preferences/ByHost, Containers, Group Containers, Saved Application State, Logs, HTTPStorages, WebKit, Cookies, Application Scripts, LaunchAgents, Logs/DiagnosticReports`; system: `Application Support, Caches, Preferences, LaunchAgents, LaunchDaemons, PrivilegedHelperTools, Logs, Logs/DiagnosticReports`.
- `strip_group_prefix`: regex `^(?:group\.)?(?:([A-Z0-9]{10})\.)?(.+)$` → `(rest, team)`.
- `other_apps`: every `.app` from `app_dirs` (same globs as `find_apps`) except `exclude`; IDs from `Info.plist` + helpers (reuse Task 1 helper extraction); names as in Task 1. Do **not** run `codesign` here. The shared-team check calls `codesign` on `others.paths` lazily, only when a team-only Group Container match exists, and caches the result.
- `find_candidates` classification per direct child, first match wins (this order is the spec's precedence):
  1. seed: `.app` (`"app"`), each `zap_paths` (`"brew zap"`, skip if equal to a location root), `roots.caskroom/info.cask` if exists (`"cask"`).
  2. skip if lowercased name (or group-stripped rest) starts with `com.apple.`.
  3. skip if the name matches an ID in `others.ids` that is longer than the target ID it matches (match = `n == id or n.startswith(id + ".")`).
  4. `n` (or stripped rest for Group Containers) matches `info.bundle_id` → `"bundle id"`; matches a helper → `"helper"`.
  5. in LaunchAgents/LaunchDaemons: plist `Program` or `ProgramArguments[0]` starts with `str(info.path)` → `"launchd"` (`plistlib` errors → skip entry).
  6. in Application Support/Caches/Logs: `n` or its stem equals a name key → `"name"`, or `"name (ambiguous)"` unchecked if key < 4 chars or key in `others.names`.
  7. Group Containers only: team prefix == `info.team_id` → `"team"`/`"team (shared)"`; stripped rest matches first two components of bundle ID → `"vendor (shared)"`.
  8. DiagnosticReports only: name starts with a name key or ID followed by one of `-_. ` → `"crash report"`.
  9. any name key or `vendor` (≥4 chars) contained in `n` → `"partial"` unchecked.
- `size` via `cleaner.get_size`. `PermissionError`/`OSError` on `iterdir` → skip that location.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add ozempic/uninstaller.py tests/test_uninstaller.py
git commit -m "feat(uninstall): leftover matcher with precedence and exclusions"
```

---

### Task 3: Removal side effects

**Files:**
- Create: `ozempic/trash.py`
- Create: `tests/test_trash.py`

**Interfaces:**
- Consumes: `Candidate`, `AppInfo` (Tasks 1–2).
- Produces (in `ozempic/trash.py`):
  - `finder_available() -> bool`
  - `hosts_terminal(info: AppInfo) -> bool`
  - `is_running(info: AppInfo) -> bool`
  - `quit_app(info: AppInfo, timeout: float = 10.0) -> bool` (True if no longer running)
  - `unload_launchd(paths: list[Path]) -> None`
  - `move_to_trash(paths: list[Path]) -> list[tuple[Path, str]]` (failures: path + reason)
  - `flush_prefs() -> None`

- [ ] **Step 1: Write the failing tests** (`subprocess.run` patched in all)

```python
class TestTrash(unittest.TestCase):
    def test_finder_available_true_on_rc0(self):
    def test_finder_available_false_on_rc1(self):
    def test_hosts_terminal(self):            # env __CFBundleIdentifier="org.alacritty", info.bundle_id "org.alacritty" -> True; other -> False
    def test_is_running_uses_pgrep_on_bundle(self):  # args == ["pgrep","-f",str(app)+"/Contents/"]
    def test_move_to_trash_passes_paths_as_argv(self):
        p = tmp / "Bob's \"Tool\" ü.app"; p.mkdir()
        move_to_trash([p])
        args = run.call_args.args[0]
        self.assertEqual(args[0], "osascript")
        self.assertEqual(args[-1], str(p))          # verbatim, after "--"
        self.assertNotIn(str(p), " ".join(args[:args.index("--")]))
    def test_move_to_trash_reports_survivors(self):  # 2 paths, mock deletes only first -> failures == [(second, <stderr>)]
    def test_move_to_trash_empty_list_no_call(self):
    def test_unload_user_agent(self):          # ~/Library/LaunchAgents/a.b.plist Label "a.b" -> ["launchctl","bootout",f"gui/{os.getuid()}/a.b"]
    def test_unload_system_daemon_uses_admin_osascript(self):  # /Library/LaunchDaemons/x.plist -> osascript ... "with administrator privileges"
    def test_flush_prefs(self):                # ["killall","-u",getpass.getuser(),"cfprefsd"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_trash -v`
Expected: ImportError.

- [ ] **Step 3: Implement in `ozempic/trash.py`**

- `finder_available`: `osascript -e 'tell application "Finder" to get name of startup disk'`, rc == 0.
- `hosts_terminal`: `os.environ.get("__CFBundleIdentifier","").lower()` in `{info.bundle_id, *info.helper_ids}` lowercased (verified: Alacritty sets `org.alacritty`).
- `quit_app`: `osascript -e f'quit app id "{bundle_id}"'` (bundle IDs are `[A-Za-z0-9.-]`; validate with regex before use, else return False), poll `is_running` every 0.5 s up to `timeout`.
- `move_to_trash`: single call; paths after `--` as argv:

```applescript
on run argv
  set fs to {}
  repeat with p in argv
    set end of fs to (POSIX file (p as text)) as alias
  end repeat
  tell application "Finder" to delete fs
end run
```

  passed as `["osascript", "-e", line1, "-e", line2, ..., "--", *map(str, paths)]`. Failures = paths that still `exists()` (or `is_symlink()`) after the call, with `stderr.strip()` or `"still present"` as the reason.
- `unload_launchd`: read `Label` with `plistlib` (skip unreadable). Under home → `launchctl bootout gui/<uid>/<label>`. Otherwise collect labels and run one `osascript -e 'do shell script "launchctl bootout system/<l1>; launchctl bootout system/<l2>" with administrator privileges'` (labels validated with the same regex; skip invalid). Ignore nonzero return (job may not be loaded). `# ponytail: Finder asks for its own admin password for root-owned paths, so a system-daemon uninstall prompts twice; merge only if it annoys.`
- `flush_prefs`: `killall -u <user> cfprefsd`, ignore rc.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add ozempic/trash.py tests/test_trash.py
git commit -m "feat(uninstall): Finder trash, launchd unload, app quit helpers"
```

---

### Task 4: Checklist UI

**Files:**
- Create: `ozempic/checklist.py`
- Create: `tests/test_checklist.py`

**Interfaces:**
- Consumes: `Candidate`, `AppInfo`; `cleaner.format_size`.
- Produces (in `ozempic/checklist.py`):
  - `class ChecklistState` with `__init__(self, items: list[Candidate])`; attributes `items`, `cursor: int`, `offset: int`; methods `move(delta: int) -> None` (clamped), `toggle() -> None`, `set_all(value: bool) -> None`, `selected() -> list[Candidate]`, `selected_size() -> int`, `scroll(height: int) -> None` (adjusts `offset` so `cursor` is within `[offset, offset+height)`).
  - `run_checklist(info: AppInfo, items: list[Candidate]) -> list[Candidate] | None`: `None` on quit.

- [ ] **Step 1: Write the failing tests**

```python
class TestChecklistState(unittest.TestCase):
    # items: 3 Candidates sizes 100/200/300, checked True/False/True
    def test_initial_selection(self):   # selected_size() == 400
    def test_toggle(self):              # cursor 1, toggle -> selected_size() == 600
    def test_move_clamps(self):         # move(-5) -> 0; move(99) -> 2
    def test_all_none(self):            # set_all(False) -> []; set_all(True) -> 3 items
    def test_scroll_follows_cursor(self):  # height 2, cursor 2 -> offset 1; cursor 0 -> offset 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_checklist -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

- `ChecklistState`: logic only, no curses import at module top level is required, but `run_checklist` imports `curses` inside the function.
- `run_checklist` with `curses.wrapper`:
  - Header line: `ozempic uninstall · <App> (<bundle id>) · <n> items · <size> selected`.
  - Group header rows (`▸ <group>`) shown above each group's first item. They are display-only; the cursor moves over items.
  - Rows: `[x]`/`[ ]`, path (relative name within group; full path for `Application`/`Homebrew`), size right-aligned, reason.
  - Footer: `↑↓/jk move · space toggle · a all · n none · enter review · q quit`.
  - Colors: if `curses.COLORS >= 256`, pairs from the logo's 256-color indexes 51 (header), 201 (cursor), 207 (unchecked dim); otherwise `A_BOLD`/`A_REVERSE`.
  - `KEY_RESIZE` redraws.
  - Enter shows a confirm screen: count, total size, and every checked path under `/Library` listed under "needs admin password". `y` returns `state.selected()`; any other key goes back. `q`/Esc returns `None`.
- Truncate long paths with `…` in the middle to fit the width.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -q`
Expected: OK.

- [ ] **Step 5: Manual check**

Run: `python3 -c "from pathlib import Path; from ozempic.checklist import run_checklist; from ozempic.uninstaller import Candidate, AppInfo; i=AppInfo(Path('/Applications/X.app'),'x.y',[],['x'],None,None,None,[]); print(run_checklist(i,[Candidate(Path(f'/tmp/f{n}'),'~/Library/Caches','name',n%2==0,n*1000) for n in range(60)]))"`
Expected: list scrolls, toggles, resizes; `q` prints `None`; enter→`y` prints the selected list.

- [ ] **Step 6: Commit**

```bash
git add ozempic/checklist.py tests/test_checklist.py
git commit -m "feat(uninstall): curses checklist with confirm screen"
```

---

### Task 5: CLI subcommands, uninstall flow, history

**Files:**
- Create: `ozempic/history.py`
- Modify: `ozempic/__main__.py` (whole file restructured)
- Modify: `ozempic/reporter.py` (add `print_candidates`, `print_uninstalled`)
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4; `cleaner.check_fda`, `cleaner.clean_all`, `cleaner.get_review_items`, `cleaner.format_size`; `reporter._print_card(title, results, total_label, total_val, is_review)` with result dicts `{"label": str, "size_str": str, "action": str | None}`.
- Produces:
  - `history.HISTORY_PATH: Path` = `Path("~/Library/Application Support/ozempic/history.log").expanduser()`
  - `history.append(entry: dict, path: Path = HISTORY_PATH) -> None`: adds `"ts"` (ISO-8601 local, seconds), writes one JSON line, creates parents; `OSError` → one warning line to stderr, no raise.
  - `reporter.print_candidates(info: AppInfo, items: list[Candidate]) -> None` (dry-run listing: group headers, `[x]`/`[ ]`, path, size, reason, then total checked)
  - `reporter.print_uninstalled(removed: list[Candidate], failed: list[tuple[Path, str]]) -> None` (card "UNINSTALLED" with "Moved to Trash" total; card "NOT REMOVED" (`is_review=True`) listing failures with reason as `action`, only if any)
  - `__main__.main(argv: list[str] | None = None) -> int` (exit code; `if __name__` block does `sys.exit(main())`)

- [ ] **Step 1: Write the failing tests** (`tests/test_main.py`; patch `cleaner.check_fda` → True, patch `history.HISTORY_PATH` to tmp)

```python
class TestRouting(unittest.TestCase):
    def test_bare_runs_clean(self):            # patch __main__.run_clean; main([]) -> called
    def test_bare_flags_route_to_clean(self):  # main(["--keep-logs","-y"]) -> run_clean called with keep_logs=True, yes=True
    def test_uninstall_routes(self):           # main(["uninstall","Obsidian","--dry-run"]) -> run_uninstall called

class TestUninstallFlow(unittest.TestCase):
    def test_dry_run_touches_nothing(self):
        # fake roots with make_app + leftovers; patch trash.move_to_trash
        rc = main(["uninstall", "Obsidian", "--dry-run"])
        self.assertEqual(rc, 0)
        move_to_trash.assert_not_called()
        # stdout contains "md.obsidian.plist" and "bundle id"
    def test_unknown_app_exit_1(self):          # main(["uninstall","Nope"]) == 1
    def test_apple_app_refused_exit_1(self):    # com.apple.* app -> 1, move_to_trash not called
    def test_hosting_terminal_refused(self):    # trash.hosts_terminal -> True -> 1, nothing trashed
    def test_finder_denied_aborts(self):        # trash.finder_available -> False -> 1, nothing trashed
    def test_quit_cancelled(self):              # is_running True, input "n" -> 1, nothing trashed
    def test_checklist_quit_trashes_nothing(self):  # run_checklist -> None -> 0, move_to_trash not called
    def test_full_run_order_and_history(self):
        # run_checklist -> [launchd plist cand, prefs plist cand, app cand]
        # assert call order: unload_launchd, move_to_trash, flush_prefs
        # history file has one JSON line with "subcommand":"uninstall", "app", paths, "failed"
    def test_no_prefs_no_flush(self):           # no .plist under Preferences selected -> flush_prefs not called
    def test_ambiguous_app_prompts(self):       # two matches, input "2" -> second app used

class TestHistory(unittest.TestCase):
    def test_append_writes_json_line(self):     # two appends -> 2 lines, each json.loads ok, has "ts"
    def test_append_oserror_does_not_raise(self):  # path under a file -> warning only
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_main -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

- `__main__.py`:
  - `argparse` with subparsers `clean` (`--keep-logs`, `-y/--yes`) and `uninstall` (`app`, `--dry-run`). Routing: if `argv` is empty, or `argv[0]` starts with `-` and isn't `-h`/`--help`, prepend `"clean"`.
  - `run_clean(keep_logs: bool, yes: bool) -> int`: today's flow moved verbatim (logo, FDA, analyze spinner, cards, prompt, clean spinner, final card). After the real clean, `history.append({"subcommand": "clean", "results": actual_cleaned})`.
  - `run_uninstall(query: str, dry_run: bool, roots: Roots | None = None) -> int`. Order:
    1. logo; FDA check (exit 1 with `print_fda_error`).
    2. `find_apps`. 0 matches → message, 1. More than 1 → numbered list plus `input()`; an invalid choice exits 1.
    3. Inside a `Spinner("Finding leftovers")`: `read_app_info` (an `UninstallError` prints and exits 1), `other_apps`, `find_candidates`.
    4. If `dry_run`: `print_candidates`, then 0.
    5. Exit 1 with a message if `hosts_terminal` is true, or if `finder_available` is false (print: System Settings → Privacy & Security → Automation → allow your terminal to control Finder).
    6. If `is_running`: prompt `"<App> is running. Quit it? (y/N)"`; anything other than `y` exits 1; if `quit_app` fails, exit 1.
    7. `run_checklist`. `None` or empty → "Nothing removed.", 0.
    8. `unload_launchd` (selected paths whose parent name is `LaunchAgents`/`LaunchDaemons`), then `move_to_trash`, then `flush_prefs` if any removed path's parent is `Preferences` or `ByHost` and ends `.plist`.
    9. `history.append({"subcommand":"uninstall","app":str(info.path),"bundle_id":...,"removed":[{"path","size"}],"failed":[{"path","reason"}]})`.
    10. `print_uninstalled`; return 0 if no failures, else 1.
- `reporter.py`: the two functions above, reusing `_print_card` and `cleaner.format_size`.

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add ozempic/__main__.py ozempic/history.py ozempic/reporter.py tests/test_main.py
git commit -m "feat: clean/uninstall subcommands, uninstall flow, history log"
```

---

### Task 6: README and end-to-end check

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README** to match the code. Remove `--scan`, `--clean` (as a flag), `--delete-backup`, the suspicious-file scanner sections and iOS backup review. Document `ozempic` / `ozempic clean [--keep-logs] [-y]`, the Docker target, `ozempic uninstall <App> [--dry-run]` (what it searches, checked vs unchecked, Trash-only, Homebrew casks, the Automation permission prompt), and the history log path. Keep the FDA instructions.

- [ ] **Step 2: Dry run against a real app**

Run: `ozempic uninstall Obsidian --dry-run`
Expected: rows include `/Applications/Obsidian.app` (app), `~/Library/Application Support/obsidian` (brew zap or name), `md.obsidian.plist` (brew zap or bundle id), `Containers/md.obsidian.quicklook` (helper), `/opt/homebrew/Caskroom/obsidian` (cask). Nothing moved; `ls /Applications/Obsidian.app` still succeeds.

- [ ] **Step 3: Real run on a throwaway app** (needs the user present: Automation and admin prompts)

Ask the user which disposable app to remove (Apple apps are refused, so it must be third-party; a small cask such as `codexbar` also exercises the Homebrew path). Run `ozempic uninstall <it>`, confirm all rows, then verify:
- the app and its rows are in `~/.Trash`
- `brew list --cask` no longer lists it (verifies the spec's [Likely] Caskroom claim; if it still lists it, report it, don't patch around it)
- Finder → Trash → Put Back on the `.app` restores it
- `tail -1 ~/Library/Application\ Support/ozempic/history.log` shows the entry.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for clean/uninstall subcommands"
```
