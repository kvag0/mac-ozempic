"""
Append-only history of what ozempic removed. One JSON object per line.
Lives outside ~/Library/Logs because `ozempic clean` empties that folder.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HISTORY_PATH = Path("~/Library/Application Support/ozempic/history.log").expanduser()


def append(entry: dict, path: Path | None = None) -> None:
    path = path or HISTORY_PATH
    record = {"ts": datetime.now().isoformat(timespec="seconds"), **entry}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"warning: could not write history to {path}: {e}", file=sys.stderr)
