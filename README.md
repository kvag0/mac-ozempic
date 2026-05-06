# mac-ozempic

macOS CLI disk cleaner. Auto-deletes known-safe caches and surfaces suspicious files.

## Install

```bash
pip install -e .
```

## Usage

```bash
ozempic              # full run: clean + scan + report
ozempic --scan       # scan only, no deletion
ozempic --clean      # clean only, skip anomaly scan
ozempic --keep-logs  # exclude logs from auto-clean
ozempic --delete-backup <id>  # delete iOS backup by UUID prefix
```

Requires **Full Disk Access** for the terminal. Enable in:  
`System Settings → Privacy & Security → Full Disk Access`

## What it cleans (auto)

| Target | Path |
|--------|------|
| User caches | `~/Library/Caches/` |
| System caches | `/Library/Caches/` |
| User logs | `~/Library/Logs/` |
| System logs | `/Library/Logs/` |
| Xcode derived data | `~/Library/Developer/Xcode/DerivedData/` |
| npm cache | `~/.npm/_cacache/` |
| pip cache | `~/Library/Caches/pip/` |
| Homebrew cache | `~/Library/Caches/Homebrew/` |
| Electron sub-caches | `GPUCache`, `Code Cache`, `CachedData` in App Support |
| Mail Downloads | `~/Library/Containers/com.apple.mail/.../Mail Downloads/` |
| QuickLook cache | via `qlmanage -r` |
| Font cache | via `atsutil databases -removeUser` |
| `.DS_Store` files | recursive in `~` |

## What it flags (review)

- **Trash** — shown with size, command to empty
- **iOS backups** — shown with device name, date, and delete command

## What it flags (suspicious)

**Location anomalies:**
- Executables in `~/Downloads/`
- Script files (`.sh`, `.py`, `.rb`, etc.) outside known tool paths
- Unexpected hidden files/dirs in `~` root
- Files >500MB in Downloads/Desktop not modified in 30+ days

**Extension mismatches:**
- Image/doc files with executable bit set
- Extensionless executable files
- Files whose actual type (via `file`) doesn't match their extension

## What it never touches

- `~/Library/Application Support/` root
- `com.apple.bird` / CloudKit sync paths
- `.lproj` language files (breaks Gatekeeper signatures)
- `/var/folders/` root

## Output

```
━━━ CLEANED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ User caches          1.2 GB
  ✓ Electron sub-caches  340 MB
  Total freed: 1.5 GB

━━━ REVIEW ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚠ Trash                4.1 GB  →  run: rm -rf ~/.Trash/*
  ⚠ iOS backup           12 GB   →  "Caio's iPhone" (2026-04-01)
                                     run: ozempic --delete-backup abc12345

━━━ SUSPICIOUS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✗ ~/Downloads/setup.sh  executable script in Downloads
  ✗ ~/Desktop/photo.jpg   has executable bit set
```
