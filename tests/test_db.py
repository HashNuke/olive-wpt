import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import db


class DatabaseTests(unittest.TestCase):
    def make_project(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "outputs" / "css" / "example-html-test").mkdir(parents=True)
        (root / "wpt_paths.txt").write_text("css/example.html\ncss/missing.html\n", encoding="utf-8")
        (root / "outputs" / "css" / "example-html-test" / "result.png").write_bytes(b"result")
        (root / "outputs" / "css" / "example-html-test" / "current.json").write_text(
            json.dumps(
                {
                    "current_diff_percent": 1.5,
                    "run_passed": True,
                    "run_outcome": "pass",
                    "result_at": "2026-08-04T10:11:12Z",
                }
            ),
            encoding="utf-8",
        )
        return temporary, root

    def test_rebuild_creates_rows_from_inventory_and_json(self):
        temporary, root = self.make_project()
        try:
            self.assertEqual(db.rebuild_database(root), 2)
            with sqlite3.connect(root / "data.sqlite") as connection:
                rows = dict(connection.execute("SELECT path, status FROM wpt_tests"))
            self.assertEqual(rows, {"css/example.html": "UNKN", "css/missing.html": "NONE"})
            with sqlite3.connect(root / "data.sqlite") as connection:
                run_data = connection.execute(
                    "SELECT run_passed, run_outcome, result_at FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()
            self.assertEqual(run_data, (1, "pass", "2026-08-04T10:11:12Z"))
        finally:
            temporary.cleanup()

    def test_upsert_updates_one_test_without_rebuilding_inventory(self):
        temporary, root = self.make_project()
        try:
            db.rebuild_database(root)
            db.upsert_test(root, "css/example.html", "FAIL")
            statuses = db.load_statuses(root / "data.sqlite")
            self.assertEqual(statuses["css/example.html"], "FAIL")
            self.assertEqual(statuses["css/missing.html"], "NONE")
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
