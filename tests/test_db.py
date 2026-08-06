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
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(wpt_tests)")
                }
                run_data = connection.execute(
                    "SELECT run_passed, run_outcome, result_at FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()
            self.assertIn("result_at", columns)
            self.assertNotIn("updated_at", columns)
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

    def test_load_test_index_includes_current_diff(self):
        temporary, root = self.make_project()
        try:
            db.rebuild_database(root)
            index = db.load_test_index(root / "data.sqlite")
            self.assertEqual(index["css/example.html"], {
                "status": "UNKN",
                "current_diff_percent": 1.5,
            })
            self.assertEqual(index["css/missing.html"], {
                "status": "NONE",
                "current_diff_percent": None,
            })
        finally:
            temporary.cleanup()

    def test_approved_unchanged_render_ignores_existing_run_mismatch(self):
        temporary, root = self.make_project()
        try:
            result_hash = db.result_hash(root / "outputs" / "css" / "example-html-test" / "result.png")
            (root / "outputs" / "css" / "example-html-test" / "metadata.json").write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "approved_result_sha256": result_hash,
                    }
                ),
                encoding="utf-8",
            )
            current_path = root / "outputs" / "css" / "example-html-test" / "current.json"
            current = json.loads(current_path.read_text(encoding="utf-8"))
            current["run_passed"] = False
            current["run_outcome"] = "pixel_mismatch"
            current_path.write_text(json.dumps(current), encoding="utf-8")

            db.rebuild_database(root)

            with sqlite3.connect(root / "data.sqlite") as connection:
                status = connection.execute(
                    "SELECT status FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()[0]
            self.assertEqual(status, "PASS")
        finally:
            temporary.cleanup()

    def test_approved_improved_render_is_pass(self):
        temporary, root = self.make_project()
        try:
            (root / "outputs" / "css" / "example-html-test" / "metadata.json").write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "approved_result_sha256": "older-render",
                        "approved_diff_percent": 2.0,
                    }
                ),
                encoding="utf-8",
            )
            current_path = root / "outputs" / "css" / "example-html-test" / "current.json"
            current = json.loads(current_path.read_text(encoding="utf-8"))
            current["current_diff_percent"] = 1.0
            current["run_passed"] = False
            current["run_outcome"] = "pixel_mismatch"
            current_path.write_text(json.dumps(current), encoding="utf-8")

            db.rebuild_database(root)

            with sqlite3.connect(root / "data.sqlite") as connection:
                status = connection.execute(
                    "SELECT status FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()[0]
            self.assertEqual(status, "PASS")
        finally:
            temporary.cleanup()

    def test_rejected_equal_pixel_diff_remains_failed(self):
        temporary, root = self.make_project()
        try:
            result_path = root / "outputs" / "css" / "example-html-test" / "result.png"
            reviewed_hash = db.result_hash(result_path)
            review_path = result_path.parent / "review-state.json"
            review_path.write_text(
                json.dumps(
                    {
                        "state": "rejected",
                        "olive_result_sha256": reviewed_hash,
                        "different_pixels": 10,
                    }
                ),
                encoding="utf-8",
            )
            result_path.write_bytes(b"new-render-with-the-same-diff")
            current_path = result_path.parent / "current.json"
            current = json.loads(current_path.read_text(encoding="utf-8"))
            current["current_different_pixels"] = 10
            current_path.write_text(json.dumps(current), encoding="utf-8")

            db.rebuild_database(root)

            with sqlite3.connect(root / "data.sqlite") as connection:
                status = connection.execute(
                    "SELECT status FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()[0]
            self.assertEqual(status, "FAIL")
        finally:
            temporary.cleanup()

    def test_rejected_strictly_lower_pixel_diff_is_reviewable(self):
        temporary, root = self.make_project()
        try:
            result_path = root / "outputs" / "css" / "example-html-test" / "result.png"
            reviewed_hash = db.result_hash(result_path)
            review_path = result_path.parent / "review-state.json"
            review_path.write_text(
                json.dumps(
                    {
                        "state": "rejected",
                        "olive_result_sha256": reviewed_hash,
                        "different_pixels": 10,
                    }
                ),
                encoding="utf-8",
            )
            result_path.write_bytes(b"new-render-with-a-lower-diff")
            current_path = result_path.parent / "current.json"
            current = json.loads(current_path.read_text(encoding="utf-8"))
            current["current_different_pixels"] = 9
            current_path.write_text(json.dumps(current), encoding="utf-8")

            db.rebuild_database(root)

            with sqlite3.connect(root / "data.sqlite") as connection:
                status = connection.execute(
                    "SELECT status FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()[0]
            self.assertEqual(status, "REVW")
        finally:
            temporary.cleanup()

    def test_ai_pass_review_state_is_reviewable(self):
        temporary, root = self.make_project()
        try:
            result_path = root / "outputs" / "css" / "example-html-test" / "result.png"
            review_path = result_path.parent / "review-state.json"
            review_path.write_text(
                json.dumps(
                    {
                        "state": "review",
                        "reason": "The render looks correct.",
                        "olive_result_sha256": db.result_hash(result_path),
                    }
                ),
                encoding="utf-8",
            )

            db.rebuild_database(root)

            with sqlite3.connect(root / "data.sqlite") as connection:
                status = connection.execute(
                    "SELECT status FROM wpt_tests WHERE path = ?",
                    ("css/example.html",),
                ).fetchone()[0]
            self.assertEqual(status, "REVW")
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
