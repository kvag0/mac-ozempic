# ozempic uninstall — Design

Date: 2026-11-18

## Intent

ozempic is a personal tool (one user, one Mac). Its job has shifted from
"reclaim disk space" to **housekeeping: keep the Mac neat**, not out of
necessity. Measured on 2026-11-18: data volume 13% full (54 GB of 460 GB),
0 `node_modules`, 16 KB in Downloads, 0 orphaned Containers. The disk is
already lean, so new features are about tidiness, not bytes.

Inspiration: [tw93/Mole](https://github.com/tw93/Mole). Its `uninstall`
command is the feature that fits tidiness best. The depth bar is
**AppCleaner**: when an app goes, everything it scattered goes with it.

Neatness is kept by **prevention** (removing leftovers at uninstall time),
not by sweeping for orphans afterwards. A heuristic orphan scan run on this
Mac flagged 13 "orphan" preference files, and 12 were Apple system daemons
(`familycircled`, `MobileMeAccounts`, ...). Sweeping is mostly false
positives. Uninstalling with full context (the `.app` is still there to
read) is precise.

## Goals

1. `ozempic uninstall <App>`: find the app and every file it left around
   the system, at AppCleaner depth, and let the user review them in an
   interactive checklist before moving the checked ones to the Trash.
2. Restructure the CLI into subcommands: `ozempic clean` (today's
   behavior) and `ozempic uninstall`.
3. Append-only history log of what ozempic removed (both subcommands).
4. README rewritten to match the code as it is now.

## Non-goals

- Distribution: Homebrew, install script, `update`/`remove` commands,
  shell completion, `--json` output. Personal tool.
- Mole's `status`, `optimize`, `slim`, `touchid`: not housekeeping.
- Mole's `purge`, `installer`, `analyze`: nothing on this Mac for them to
  find today.
- AppCleaner's SmartDelete (background watcher for apps dragged to the
  Trash): needs a daemon. Add only if missed.
- Kernel extensions and system extensions (need `systemextensionsctl` and
  user approval in System Settings).
- Background Task Management login items (`sfltool dumpbtm` needs root
  and its output format is unstable).
- A sweeping orphan scanner (see Intent).
- **pkg receipts** (`pkgutil --files` / `--forget`). Cut during review:
  only 2 non-Apple receipts exist on this Mac (`sh.brew.homebrew`,
  `com.tailscale.ipn.macsys`), and vendor-prefix receipt matching was the
  riskiest part (shared vendor directories). Revisit if a pkg-installed
  app leaves something behind.

## Anti-goals (failure even if it works)

- **Permanent deletion.** `uninstall` never calls `rm`/`shutil.rmtree`.
  Everything goes to the Trash with Put Back available. If the Trash path
  fails, abort and say why; no fallback to deletion.
- **Touching another installed app's files.** A shared Team ID, a generic
  app name, or a vendor-level folder must never make another app's data
  checked by default.
- **Removing Apple software.** Refuse apps under `/System/Applications`
  and any bundle ID starting with `com.apple.`.
- **Breaking ozempic's branding.** Same logo, gradient, card style,
  emoji icons, spinner.
- **New dependencies.** Stays stdlib-only.

## Constraints

- Python stdlib only (`curses`, `plistlib`, `subprocess`, `pathlib`).
  `curses` confirmed available on this machine's Python 3.11.8.
- `pyproject.toml` says `requires-python = ">=3.9"`, but the code already
  uses `dict | None` annotations without `from __future__ import
  annotations`, which fails on 3.9. Bump to `>=3.10` (builder's call:
  bump, or add the future import).
- Tests use `unittest` (pytest is not installed). 16 tests pass today.
- Full Disk Access is already required by `clean` (`check_fda()`);
  `uninstall` requires it too, since Containers and Group Containers are
  unreadable without it.
- **The history log must not live in `~/Library/Logs`**: `clean` empties
  that directory, so it would wipe its own log. Put it at
  `~/Library/Application Support/ozempic/history.log` (`clean` never
  touches the root of Application Support; it only removes
  `GPUCache`/`Code Cache`/`CachedData` subfolders).

## Approaches considered

1. **Interactive full-screen checklist with `curses`** (chosen). Files
   grouped by location, sizes shown, keyboard toggling, confirm screen.
   Closest to AppCleaner, and the user is the final filter on false
   positives, which is what makes deep matching safe.
2. Numbered list plus "type the numbers to keep" prompt. Same search
   depth, about half the UI code, clunkier. Rejected: the user wanted the
   AppCleaner experience.
3. Don't build: install Mole (`mo uninstall`) or keep AppCleaner.app.
   Zero code, but it isn't ozempic. Rejected: the user wants their own
   branding. Mole is GPL-3.0 and ozempic is MIT, so **no Mole code or path
   tables are copied**; behavior is rebuilt from macOS conventions.

### Homebrew casks (decided by the user)

9 of the non-Apple apps on this Mac are Homebrew casks (obsidian,
raycast, docker-desktop, whatsapp, claude, stats, codexbar,
tailscale-app, blender). Options considered:

1. **Merge the cask's `zap` list into the checklist and trash the
   Caskroom entry via Finder** (chosen). Homebrew maintains a curated
   leftover list per cask; `brew info --cask --json=v2 <token>` exposes it
   (verified for `obsidian`: Application Support, prefs plist, saved
   state, recent-documents `.sfl*`). Trashing
   `/opt/homebrew/Caskroom/<token>` makes Homebrew stop treating the cask
   as installed [Likely; builder to verify with `brew list --cask`].
   Put Back still restores everything.
2. Delegate to `brew uninstall --cask --zap`. Rejected: deletes
   permanently, breaks the Trash-only anti-goal.
3. Ignore Homebrew. Rejected: `brew` keeps listing the app and
   `brew upgrade` may reinstall it.

## CLI

```
ozempic                       # same as `ozempic clean` (backward compatible)
ozempic clean [--keep-logs] [-y]
ozempic uninstall <App> [--dry-run]
```

- `<App>`: an app name ("Obsidian", case-insensitive), a `.app` path, or
  a bundle ID. Search `/Applications`, `/Applications/*/` (one level of
  subfolders, e.g. `/Applications/Utilities`) and `~/Applications`. If
  several apps match, list them and ask which one (plain numbered prompt
  is fine here). If none match, say so and exit non-zero.
- `--dry-run`: print the found files grouped by location with their
  default check state and sizes, then exit. No checklist, no Trash.
  Used for testing and for "what would this remove?".

## How uninstall finds files

### Search keys (gathered from the `.app` before anything is removed)

1. **Bundle ID** of the app (`Contents/Info.plist` → `CFBundleIdentifier`).
2. **Helper bundle IDs**: every embedded bundle's `CFBundleIdentifier`
   under `Contents/Library/LoginItems`, `Contents/Library/LaunchServices`,
   `Contents/XPCServices`, `Contents/PlugIns`, `Contents/Frameworks/*.app`,
   `Contents/Helpers`. These are what leave LaunchAgents, helper tools and
   extension containers behind.
3. **App name**: `CFBundleName`, `CFBundleDisplayName`, and the `.app`
   file name without extension. Lowercased; also a variant with spaces
   removed.
4. **Team ID**: `codesign -dv --verbose=2 <app>` → `TeamIdentifier`.
   Unsigned/ad-hoc apps have none; skip this key.
5. **Vendor key**: the second component of the bundle ID, lowercased
   (`com.brave.Browser` → `brave`, `md.obsidian` → `obsidian`). Used only
   for unchecked partial matches. Skipped if under 4 characters. Exists
   because vendor folders don't match the app name: Brave's 239 MB profile
   lives in `Application Support/BraveSoftware`.
6. **Cask token**: if the app is a Homebrew cask, its token and `zap`
   paths. Find the token by matching the `.app` against
   `brew info --cask --json=v2 --installed` artifacts (builder's call on
   the exact lookup; `brew` absent means no cask handling). Expand `~` and
   globs in `zap` `trash`/`delete` entries; ignore `rmdir`, `launchctl`,
   `pkgutil`, `script` and `signal` stanzas.

### Locations searched

User (`~/Library/...`): `Application Support`, `Caches`, `Preferences`,
`Preferences/ByHost`, `Containers`, `Group Containers`,
`Saved Application State`, `Logs`, `HTTPStorages`, `WebKit`, `Cookies`,
`Application Scripts`, `LaunchAgents`, `Logs/DiagnosticReports`.

System (`/Library/...`): `Application Support`, `Caches`, `Preferences`,
`LaunchAgents`, `LaunchDaemons`, `PrivilegedHelperTools`, `Logs`,
`Logs/DiagnosticReports`.

Only **direct children** of each location are matched (plus files inside
DiagnosticReports), never a recursive walk of `~/Library`.

### Matching rules and default check state

| Match | Example | Default |
|-------|---------|---------|
| The `.app` itself | `/Applications/Obsidian.app` | checked |
| Name equals a bundle ID or helper ID, or starts with `<id>.` | `com.raycast.macos.plist`, `com.foo.app.helper` | checked |
| Container named with the bundle ID or a helper ID | `Containers/net.whatsapp.whatsapp.serviceextension` | checked |
| Group Container whose name, **after stripping a leading `group.` and/or `<TEAMID>.`**, equals or starts with the bundle ID or a helper ID | `SY64MV22J9.com.raycast.macos.shared`, `group.W5364U7YZB.io.tailscale.shared`, `group.com.docker` | checked (a bundle-ID match beats the shared-Team-ID rule) |
| Group Container that, after stripping, matches only the vendor prefix (first two bundle-ID components) | `group.net.whatsapp.family` | unchecked (vendor-level, likely shared) |
| Homebrew cask `zap` path that exists on disk | `~/Library/Saved Application State/md.obsidian.savedState` | checked |
| Homebrew Caskroom entry | `/opt/homebrew/Caskroom/obsidian` | checked |
| LaunchAgent/Daemon whose label matches a key, **or** whose `Program`/`ProgramArguments` points inside the `.app` | `com.docker.vmnetd.plist` | checked |
| `PrivilegedHelperTools` entry matching a key | `com.docker.vmnetd` | checked |
| Exact app-name match (case-insensitive, spaces-removed variant counts) in Application Support / Caches / Logs | `Application Support/obsidian` | checked, unless the name is under 4 characters or equals another installed app's name |
| Group Container `<TEAMID>.*` or `group.<TEAMID>.*` with no bundle-ID match | `UBF8T346G9.Office` | checked only if **no other installed app** shares the Team ID; otherwise unchecked |
| Partial match: a name key or the vendor key contained in the entry name | `Application Support/BraveSoftware`, `Application Support/Obsidian Helper Data` | unchecked |
| Crash reports whose file name starts with the app name or a key | `Obsidian-2026-10-01-....ips` | checked |

Every row in the checklist shows **why** it matched (bundle ID, helper,
name, vendor, team, launchd target, brew zap) so the user can judge
unchecked rows.

When one path matches several rules, the most specific rule sets its
state, in this order: `.app` / brew zap / Caskroom, bundle ID, helper ID,
launchd target, exact name, Team ID, vendor-prefix Group Container,
partial match.

Hard exclusions for heuristic matches: anything under a `com.apple.*`
name, the root of each searched location, and anything belonging to
another installed app's bundle ID or helper IDs. Brew `zap` paths are
curated by Homebrew and bypass the `com.apple.*` name rule (Obsidian's zap
list includes a file inside `com.apple.sharedfilelist`), but never the
location-root rule.

## Checklist UI (curses)

```
 ozempic uninstall · Obsidian (md.obsidian) · 14 items · 512 MB selected

 ▸ Application                                         
   [x] /Applications/Obsidian.app              372 MB  app
 ▸ ~/Library/Application Support
   [x] obsidian                                 35 MB  name
 ▸ ~/Library/Containers
   [x] md.obsidian.quicklook                    48 KB  helper
 ▸ ~/Library/Preferences
   [x] md.obsidian.plist                         4 KB  bundle id
 ▸ ~/Library/Saved Application State
   [x] md.obsidian.savedState                   12 KB  brew zap
 ▸ Homebrew
   [x] /opt/homebrew/Caskroom/obsidian           8 KB  cask

 ↑↓/jk move · space toggle · a all · n none · enter review · q quit
```

- Uses ozempic's gradient colors (cyan → magenta) when the terminal
  supports 256 colors; falls back to plain attributes otherwise.
- Scrolls when the list is longer than the window; handles resize.
- **Enter** opens a confirm screen: count, total size, and the list of
  checked system (`/Library`) paths called out, since those trigger an
  admin password prompt. `y` proceeds, anything else returns to the list.
- After `curses` exits, print the result in the existing reporter card
  style: an "UNINSTALLED" card listing what went to the Trash and the
  total, plus a card for anything that failed with the reason.

## Removing

Order of operations for the checked items:

0. **Probe Finder Automation** before any change (a harmless Finder
   AppleScript call). If denied, explain how to allow it and abort with
   nothing touched.
1. **App running?** Refuse outright if the target app hosts the terminal
   ozempic is running in. Otherwise, if the app (or a helper) is running,
   ask to quit it (`osascript -e 'quit app id "<bundle id>"'`), wait
   briefly, and abort if it's still running.
2. **Unload launchd jobs** that are about to be trashed:
   `launchctl bootout gui/<uid>/<label>` for user agents; for system
   agents/daemons the bootout needs root and should share the single
   admin prompt (builder's choice of mechanism, e.g. one
   `osascript ... with administrator privileges` call).
3. **Move to Trash via Finder**, one AppleScript call with all paths:
   `tell application "Finder" to delete {POSIX file "...", ...}`. Finder
   gives Put Back, asks for the admin password itself for root-owned
   paths, and can remove Containers that Terminal may be denied. The
   first run triggers a macOS Automation prompt (Terminal → Finder); if it
   is denied, explain how to allow it and abort.
4. **Flush the preferences cache** if any `.plist` in Preferences was
   trashed, so `cfprefsd` doesn't write it back (e.g.
   `killall -u $USER cfprefsd`; builder to confirm the safest form).
5. **Append to the history log.**

## History log

`~/Library/Application Support/ozempic/history.log`, one JSON object per
line: timestamp, subcommand, app/target, each path removed with size,
and failures. `clean` writes one entry per run with its per-target
results. No `history` subcommand; read the file directly.

## Also in this change

- `ozempic clean` subcommand wraps today's flow unchanged; bare `ozempic`
  keeps working.
- README rewritten. It currently documents `--scan`, `--clean`,
  `--delete-backup` and the suspicious-file scanner, all removed in
  `e265bc5`.
- Version/tagline in `reporter.print_logo()` stay as they are (branding).

## Testing

- `unittest`, matching the existing suite.
- Matcher tests against a temp directory laid out as a fake home and fake
  `/Library`, with a fake `.app` bundle (Info.plist, an embedded helper
  with its own bundle ID). Cover each matching-table row, rule precedence,
  the Team-ID shared case, the `group.`/Team-ID prefix stripping (use the
  real names from this Mac listed above), the short/duplicate-name case,
  the `com.apple.` exclusion, and a canned `brew info` JSON with a `zap`
  glob. Search roots must be injectable for this.
- Checklist state (toggle, all/none, selected size) tested as plain
  logic, separate from `curses` drawing.
- Finder, `launchctl`, `codesign`, `osascript`, `brew` calls are
  mocked; no test touches the real system.
- One manual end-to-end run: install a small throwaway app, run
  `ozempic uninstall <it> --dry-run`, then for real, then Put Back from
  the Trash to prove reversibility.

## Left to the builder

- Module layout (e.g. `uninstaller.py` for finding/removing, a separate
  module for the `curses` checklist).
- How the single admin prompt is shared between system launchd bootout
  and Finder.
- Exact `brew` lookup from `.app` to cask token.
- Crash-report name delimiter handling.
- Exact wait/timeout when quitting a running app.
- Python version fix (bump `requires-python` or add future import).
