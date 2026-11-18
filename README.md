# mac-ozempic

macOS CLI housekeeper. Cleans known-safe caches, and uninstalls apps together
with everything they left around the system.

## Install

```bash
pip install -e .
```

Requires Python 3.10+ and **Full Disk Access** for your terminal:
`System Settings → Privacy & Security → Full Disk Access`.

## Usage

```bash
ozempic                            # same as `ozempic clean`
ozempic clean [--keep-logs] [-y]   # show what can be cleaned, confirm, clean
ozempic uninstall <App>            # find an app's leftovers, pick, move to Trash
ozempic uninstall <App> --dry-run  # list what would be removed, touch nothing
```

`<App>` is an app name (`Obsidian`, case-insensitive), a bundle ID
(`md.obsidian`), or a path to the `.app`.

## clean

Analyzes first (dry run), shows the result, asks before deleting. `-y` skips
the prompt.

| Target | Path |
|--------|------|
| User caches | `~/Library/Caches/` |
| System caches | `/Library/Caches/` |
| User logs | `~/Library/Logs/` (skipped with `--keep-logs`) |
| System logs | `/Library/Logs/` (skipped with `--keep-logs`) |
| Xcode derived data | `~/Library/Developer/Xcode/DerivedData/` |
| npm cache | `~/.npm/_cacache/` |
| pip cache | `~/Library/Caches/pip/` |
| Homebrew cache | `~/Library/Caches/Homebrew/` |
| Docker | stopped containers, unused images, build cache (`docker ... prune`) |
| Electron sub-caches | `GPUCache`, `Code Cache`, `CachedData` in Application Support |
| Mail Downloads | `~/Library/Containers/com.apple.mail/.../Mail Downloads/` |
| QuickLook cache | via `qlmanage -r` |
| Font cache | via `atsutil databases -removeUser` |
| `.DS_Store` files | recursive in `~` |

Shown for review, never deleted automatically: the Trash, and unused Docker
volumes (they may hold database data).

## uninstall

Works like AppCleaner. It reads the app before removing anything and searches
by bundle ID, embedded helper IDs, app name, vendor name and Team ID:

- `~/Library`: Application Support, Caches, Preferences (+ ByHost),
  Containers, Group Containers, Saved Application State, Logs, HTTPStorages,
  WebKit, Cookies, Application Scripts, LaunchAgents, DiagnosticReports
- `/Library`: Application Support, Caches, Preferences, LaunchAgents,
  LaunchDaemons, PrivilegedHelperTools, Logs, DiagnosticReports
- **Homebrew casks**: the cask's curated `zap` leftover list is added, and the
  `Caskroom` entry is removed too so `brew` stops tracking the app.

Then it opens a checklist:

```
 ▸ ~/Library/Application Support
   [x] obsidian                                 35 MB  brew zap
   [ ] BraveSoftware                           252 MB  partial
 ↑↓/jk move · space toggle · a all · n none · enter review · q quit
```

Exact matches (bundle ID, helpers, launchd jobs pointing into the app, cask
`zap` paths named after the app) start **checked**. Guesses start
**unchecked**: partial names, vendor-level or shared-Team-ID Group Containers,
names or IDs shared with another installed app, and `zap` paths that look
shared or live outside `~/Library` (shown as `brew zap (shared?)`, e.g.
`~/.docker`). Each row shows why it matched.

Safety:

- Everything goes to the **Trash via Finder**, so Put Back works. Nothing is
  deleted permanently. If Finder fails, ozempic stops and says why.
- Apple apps (`/System/Applications`, `com.apple.*`) are refused.
- Files owned by another installed app are never checked by default.
- Symlinks are moved to the Trash themselves; their targets are never touched.
- A running app is quit first (you're asked). The app hosting your terminal is
  refused.
- launchd jobs are unloaded before their plists go to the Trash; `cfprefsd` is
  restarted so deleted preferences aren't written back.

First run triggers a macOS **Automation** prompt (your terminal → Finder).
Allow it, or enable it later in
`System Settings → Privacy & Security → Automation`. Removing files under
`/Library` asks for your admin password.

## History

Every `clean` and `uninstall` run appends one JSON line to
`~/Library/Application Support/ozempic/history.log` (not `~/Library/Logs`,
which `clean` empties).

```bash
tail -n 5 ~/Library/Application\ Support/ozempic/history.log
```

## Never touched

- `~/Library/Application Support/` root
- `com.apple.bird` / CloudKit sync paths
- `.lproj` language files (breaks Gatekeeper signatures)
- `/var/folders/` root
