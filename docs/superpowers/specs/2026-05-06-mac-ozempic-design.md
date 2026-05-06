# mac-ozempic Design Spec

## Overview

`ozempic` is a macOS CLI disk cleaner. It auto-deletes known-safe ephemeral files, surfaces review candidates (Trash, iOS backups), and flags anomalous/suspicious files. Goal: precision over aggression.

## Architecture

```
ozempic/
├── __main__.py     # CLI entry point (argparse), orchestrates run
├── cleaner.py      # Auto-deletes known-safe targets, collects sizes
├── scanner.py      # Detects anomalies: location + extension mismatches
└── reporter.py     # ANSI-colored structured terminal output
pyproject.toml
```

## CLI

```
ozempic                        # full run: FDA check → clean → scan → report
ozempic --scan                 # scan only, no deletion
ozempic --clean                # clean only, skip anomaly scan
ozempic --keep-logs            # exclude logs from auto-clean
ozempic --delete-backup <id>   # delete a specific iOS backup by ID
```

## Cleaner targets (auto-delete)

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
| Electron sub-caches | `GPUCache/`, `Code Cache/`, `CachedData/` in `~/Library/Application Support/*/` |
| Mail Downloads | `~/Library/Containers/com.apple.mail/.../Mail Downloads/` |
| QuickLook cache | via `qlmanage -r` |
| Font cache | via `atsutil databases -removeUser` |
| `.DS_Store` files | recursive in `~` |

## Review candidates (not auto-deleted)

| Target | Path |
|--------|------|
| Trash | `~/.Trash/` |
| iOS backups | `~/Library/Application Support/MobileSync/Backup/` |

## Blacklisted (never touched)

- `~/Library/Application Support/` root
- `com.apple.bird` (iCloud sync)
- `.lproj` files
- `/var/folders/` root

## Scanner — anomaly detection

Layer 1 — Location anomalies:
- Executables in `~/Downloads/`
- `.sh/.py/.rb` scripts outside known tool paths
- Unexpected hidden files/dirs in `~` root
- Files >500MB in Downloads/Desktop older than 30 days

Layer 2 — Extension mismatches:
- Image/doc files with executable bit
- Extensionless executable files
- `file` command output vs declared extension mismatch

## FDA check

Runs first. Queries TCC database. Exits with instructions if FDA not granted.

## Reporter output format

```
━━━ CLEANED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ User caches          1.2 GB
  Total freed: 1.2 GB

━━━ REVIEW ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚠ Trash                4.1 GB  →  run: rm -rf ~/.Trash/*

━━━ SUSPICIOUS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✗ ~/Downloads/setup.sh  executable script in Downloads
```
