import importlib.util
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "bin/update-wpt"
LOADER = SourceFileLoader("update_wpt", str(SCRIPT))
SPEC = importlib.util.spec_from_loader("update_wpt", LOADER)
assert SPEC
update_wpt = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(update_wpt)


class UpdateWptTests(unittest.TestCase):
    def test_latest_tag_uses_numeric_order(self):
        remote_tags = (
            "a\trefs/tags/merge_pr_61692\n"
            "b\trefs/tags/merge_pr_61702\n"
            "c\trefs/tags/merge_pr_9999\n"
        )
        with patch.object(update_wpt, "run", return_value=remote_tags):
            self.assertEqual(
                update_wpt.latest_wpt_tag(Path("/wpt"), "origin"),
                "merge_pr_61702",
            )

    def test_inventory_reads_reftest_links_and_excludes_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "css").mkdir()
            (root / "html").mkdir()
            (root / "tools").mkdir()
            (root / "css/static.html").write_text(
                '<link rel="match" href="ref.html">', encoding="utf-8"
            )
            (root / "html/scripted.html").write_text(
                '<link rel="mismatch" href="ref.html"><script>run()</script>',
                encoding="utf-8",
            )
            (root / "tools/template.html").write_text(
                '<link rel="match" href="ref.html">', encoding="utf-8"
            )
            (root / "css/plain.html").write_text("<p>not a reftest</p>", encoding="utf-8")

            self.assertEqual(
                update_wpt.inventory_paths(root),
                ["css/static.html", "html/scripted.html"],
            )

    def test_prune_removes_only_stale_test_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            expected = update_wpt.output_directory(output_root, "css/example.html")
            stale = output_root / "old" / "removed-html-test"
            expected.mkdir(parents=True)
            stale.mkdir(parents=True)
            (stale / "reference.png").write_bytes(b"stale")

            self.assertEqual(
                update_wpt.prune_stale_output_directories(output_root, ["css/example.html"]),
                1,
            )
            self.assertTrue(expected.is_dir())
            self.assertFalse(stale.exists())

    def test_failed_references_are_removed_from_active_inventory(self):
        report = {
            "results": [
                {"path": "ok.html", "status": "ok"},
                {"path": "request-failure.html", "status": "ok_with_request_failures"},
                {"path": "timeout.html", "status": "timeout"},
            ]
        }
        self.assertEqual(
            update_wpt.failed_reference_paths(
                report, ["ok.html", "request-failure.html", "timeout.html"]
            ),
            ["timeout.html"],
        )


if __name__ == "__main__":
    unittest.main()
