import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ReportImagePresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.outputs_root = Path(self.temp_directory.name) / "outputs"
        self.test = app.WptTest(
            path="css/example.html",
            url="https://wpt.live/css/example.html",
            review_url="/test-report/view?path=css%2Fexample.html",
        )
        self.artifact_directory = self.outputs_root / "css" / "example-html-test"
        self.outputs_patch = patch.object(app, "OUTPUTS_ROOT", self.outputs_root)
        self.outputs_patch.start()
        self.results_path = Path(self.temp_directory.name) / "current" / "result.csv"
        self.progress_path = Path(self.temp_directory.name) / "current" / "progress.json"
        self.results_patch = patch.object(app, "WPT_RESULTS_FILE", self.results_path)
        self.progress_patch = patch.object(app, "WPT_PROGRESS_FILE", self.progress_path)
        self.results_patch.start()
        self.progress_patch.start()

    def tearDown(self):
        self.outputs_patch.stop()
        self.results_patch.stop()
        self.progress_patch.stop()
        self.temp_directory.cleanup()

    def write_artifact(self, name):
        self.artifact_directory.mkdir(parents=True, exist_ok=True)
        (self.artifact_directory / name).write_bytes(b"png")

    def write_current_comparison(self, diff_percent):
        self.artifact_directory.mkdir(parents=True, exist_ok=True)
        (self.artifact_directory / "current.json").write_text(
            json.dumps(
                {
                    "current_diff_percent": diff_percent,
                    "current_different_pixels": 10,
                    "current_total_pixels": 100,
                }
            ),
            encoding="utf-8",
        )

    def test_diff_requires_both_result_and_reference(self):
        self.write_artifact("reference.png")
        availability = app.render_availability(self.test)
        self.assertFalse(availability["olive"])
        self.assertTrue(availability["reference"])
        self.assertFalse(availability["diff"])

        self.write_artifact("result.png")
        self.assertTrue(app.render_availability(self.test)["diff"])

    def test_available_image_has_heading_link_but_image_is_not_a_link(self):
        self.write_artifact("result.png")
        context = app.render_context(self.test, "olive")
        html = app.templates.get_template("render-panel.html").render(**context)
        self.assertIn(">[Open image]</a>", html)
        self.assertIn("<img ", html)
        self.assertNotIn("<a href=\"/test-report/image", html)

    def test_missing_image_has_no_open_image_link(self):
        context = app.render_context(self.test, "olive")
        html = app.templates.get_template("render-panel.html").render(**context)
        self.assertNotIn("Open image", html)
        self.assertIn("is not available", html)

    def test_review_state_records_reason_and_marks_improved_result_for_review(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(5.0)

        app.write_review_state(self.test, "Text is vertically misaligned")
        rejected = app.report_context(self.test)
        self.assertEqual(rejected["review_status"], "rejected")
        self.assertEqual(rejected["review_reason"], "Text is vertically misaligned")

        (self.artifact_directory / "result.png").write_bytes(b"improved-render")
        self.write_current_comparison(2.0)
        improved = app.report_context(self.test)
        self.assertEqual(improved["review_status"], "improved")
        self.assertEqual(app.home_status(self.test), "REVW")

        app.delete_review_state(self.test)
        self.assertFalse(app.review_state_path_for_wpt_path(self.test.path).exists())

    def test_home_status_is_none_without_an_olive_render(self):
        self.write_artifact("reference.png")
        self.assertEqual(app.home_status(self.test), "NONE")

    def test_stale_csv_cannot_hide_missing_olive_render(self):
        self.write_artifact("reference.png")
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        self.results_path.write_text(
            "status,path\nUNKN,css/example.html\n", encoding="utf-8"
        )
        self.assertEqual(app.result_status(self.test), "NONE")
        self.assertEqual(
            app.indexed_result_status(self.test, {self.test.path: "UNKN"}),
            "NONE",
        )

    def test_result_status_progress_records_new_pass_and_regression(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(0.0)
        app.write_result_statuses((self.test,))
        self.assertEqual(app.load_result_statuses(self.results_path)[self.test.path], "UNKN")

        metadata = {
            "status": "approved",
            "approved_result_sha256": app.result_sha256(self.test),
            "approved_diff_percent": 0.0,
        }
        (self.artifact_directory / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        app.write_result_statuses((self.test,))
        progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
        self.assertEqual(progress["new_passes"], 1)
        self.assertEqual(progress["regressions"], 0)

        app.write_review_state(self.test, "Regression")
        app.write_result_statuses((self.test,))
        progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
        self.assertEqual(progress["regressions"], 1)

    def test_approval_creates_missing_metadata_for_available_render(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(0.0)

        app.write_approval_status(self.test, "approved")

        metadata = json.loads(
            (self.artifact_directory / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["status"], "approved")
        self.assertEqual(metadata["wpt_local_path"], self.test.path)
        self.assertEqual(metadata["wpt_url"], self.test.url)

    def test_home_template_contains_status_tabs_and_filterable_rows(self):
        html = app.templates.get_template("home.html").render(
            tests=[{"test": self.test, "status": "NONE"}],
            status_tabs=app.HOME_STATUS_TABS,
            status_counts={"ALL": 1, "PASS": 0, "FAIL": 0, "REVW": 0, "UNKN": 0, "NONE": 1},
        )
        self.assertIn('data-status-tab="ALL"', html)
        self.assertIn('data-status-tab="NONE"', html)
        self.assertIn('data-status-item="NONE"', html)
        self.assertIn("No tests have this status.", html)
        self.assertIn("Reconcile results", html)

    def test_reconcile_results_rebuilds_the_status_index_on_demand(self):
        with patch.object(app, "load_wpt_tests", return_value=(self.test,)) as load_tests:
            with patch.object(app, "write_result_statuses") as write_statuses:
                with patch.object(app, "run_build_db") as build_db:
                    response = app.reconcile_results()

        self.assertEqual(response.status_code, 204)
        load_tests.assert_called_once_with()
        write_statuses.assert_called_once_with((self.test,))
        build_db.assert_called_once_with()

    def test_approval_does_not_rebuild_the_full_status_index(self):
        with patch.object(app, "get_wpt_test", return_value=self.test):
            with patch.object(app, "write_approval_status"):
                with patch.object(app, "delete_review_state"):
                    with patch.object(app, "write_result_statuses") as write_statuses:
                        with patch.object(app, "update_database_test") as update_db:
                            with patch.object(app, "stage_test_output") as stage_output:
                                with patch.object(app, "approval_response", return_value="updated"):
                                    response = app.approve_test(None, self.test.path)

        self.assertEqual(response, "updated")
        write_statuses.assert_not_called()
        update_db.assert_called_once_with(self.test)
        stage_output.assert_called_once_with(self.test)

    def test_review_title_has_wrapping_class_for_long_wpt_paths(self):
        html = app.templates.get_template("test-review.html").render(
            test=self.test,
            result_status="NONE",
            render_labels=app.RENDER_LABELS,
            render_availability={name: False for name in app.RENDER_LABELS},
            render_name="olive",
            render_label="Olive",
            render_available=False,
            image_url="/test-report/image",
            rejected=False,
            review_state_available=False,
            review_status="pending",
            review_reason=None,
            approval_status="pending",
            metadata_available=False,
            olive_available=False,
            current_result_sha256=None,
            current_reference_sha256=None,
            reviewed_result_sha256=None,
            approved_result_sha256=None,
            approved_baseline_available=False,
            current_comparison_available=False,
            current_diff_percent=None,
            approved_diff_percent=None,
            comparison_status="unavailable",
            comparison_passed=None,
            comparison_outcome="pending",
        )
        self.assertIn('<h1 class="test-path-title">css/example.html</h1>', html)

    def test_approval_controls_show_approve_without_preexisting_metadata(self):
        html = app.templates.get_template("approval-controls.html").render(
            test=self.test,
            result_status="UNKN",
            approval_status="pending",
            review_status="pending",
            review_reason=None,
            rejected=False,
            metadata_available=False,
            olive_available=True,
            current_comparison_available=True,
            current_result_sha256="current",
            approved_result_sha256=None,
            current_diff_percent=0.0,
            approved_diff_percent=None,
            comparison_status="awaiting approval",
        )
        self.assertIn("Approve current Olive render", html)
        self.assertIn('rows="3"', html)

    def test_base_template_contains_transient_action_toast(self):
        html = app.templates.get_template("base.html").render()
        self.assertIn('id="toast"', html)


if __name__ == "__main__":
    unittest.main()
