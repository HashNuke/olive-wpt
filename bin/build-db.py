#!/usr/bin/env python3

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from db import rebuild_database  # noqa: E402


if __name__ == "__main__":
    count = rebuild_database(PROJECT_ROOT)
    print(f"WPT_DB_REBUILT tests={count} database={PROJECT_ROOT / 'data.sqlite'}")
