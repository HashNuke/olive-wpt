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

    def tearDown(self):
        self.outputs_patch.stop()
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

    def test_current_json_run_failure_is_visible_without_csv(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(1.0)
        current_path = self.artifact_directory / "current.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["run_passed"] = False
        current["run_outcome"] = "pixel_mismatch"
        current_path.write_text(json.dumps(current), encoding="utf-8")
        self.assertEqual(app.result_status(self.test), "FAIL")

    def test_approved_unchanged_render_is_not_marked_fail_for_existing_mismatch(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(1.0)
        current_path = self.artifact_directory / "current.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["run_passed"] = False
        current["run_outcome"] = "pixel_mismatch"
        current_path.write_text(json.dumps(current), encoding="utf-8")
        (self.artifact_directory / "metadata.json").write_text(
            json.dumps(
                {
                    "status": "approved",
                    "approved_result_sha256": app.result_sha256(self.test),
                    "approved_diff_percent": 1.0,
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(app.result_status(self.test), "PASS")

    def test_missing_olive_render_is_none_without_csv(self):
        self.write_artifact("reference.png")
        self.assertEqual(app.result_status(self.test), "NONE")

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
        self.assertIn("Rebuild database", html)

    def test_reconcile_results_rebuilds_the_status_index_on_demand(self):
        with patch.object(app, "run_build_db") as build_db:
            response = app.reconcile_results()

        self.assertEqual(response.status_code, 204)
        build_db.assert_called_once_with()

    def test_approval_does_not_rebuild_the_full_status_index(self):
        with patch.object(app, "get_wpt_test", return_value=self.test):
            with patch.object(app, "write_approval_status"):
                with patch.object(app, "delete_review_state"):
                    with patch.object(app, "update_database_test") as update_db:
                        with patch.object(app, "stage_test_output") as stage_output:
                            with patch.object(app, "approval_response", return_value="updated"):
                                response = app.approve_test(None, self.test.path)

        self.assertEqual(response, "updated")
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
        self.assertIn(">Approve</button>", html)
        self.assertIn(">Reject</button>", html)
        self.assertIn('rows="3"', html)

    def test_approval_controls_show_run_failure_reason(self):
        html = app.templates.get_template("approval-controls.html").render(
            test=self.test,
            result_status="FAIL",
            approval_status="pending",
            review_status="pending",
            review_reason=None,
            rejected=False,
            metadata_available=False,
            olive_available=True,
            current_comparison_available=True,
            current_result_sha256="current",
            approved_result_sha256=None,
            current_diff_percent=1.0,
            approved_diff_percent=None,
            comparison_status="awaiting approval",
            run_passed=False,
            run_outcome="pixel_mismatch",
            run_detail="no match reference matched",
        )
        self.assertIn("Run failed: pixel_mismatch", html)
        self.assertIn("no match reference matched", html)

    def test_base_template_contains_transient_action_toast(self):
        html = app.templates.get_template("base.html").render()
        self.assertIn('id="toast"', html)


if __name__ == "__main__":
    unittest.main()
