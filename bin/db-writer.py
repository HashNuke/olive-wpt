#!/usr/bin/env python3

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from db import ensure_database, upsert_test  # noqa: E402


def main() -> None:
    rebuilt = ensure_database(PROJECT_ROOT)
    print(json.dumps({"ready": True, "rebuilt": rebuilt}), flush=True)
    for line in sys.stdin:
        path = line.strip()
        if not path:
            continue
        try:
            request = json.loads(path)
            wpt_path = request["path"]
            if not isinstance(wpt_path, str) or not wpt_path:
                raise ValueError("path must be a non-empty string")
            upsert_test(PROJECT_ROOT, wpt_path)
            print(json.dumps({"ok": True, "path": wpt_path}), flush=True)
        except Exception as error:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(error)}), flush=True)


if __name__ == "__main__":
    main()
