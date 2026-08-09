import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

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

    def write_current_comparison(self, diff_percent, different_pixels=10):
        self.artifact_directory.mkdir(parents=True, exist_ok=True)
        (self.artifact_directory / "current.json").write_text(
            json.dumps(
                {
                    "current_diff_percent": diff_percent,
                    "current_different_pixels": different_pixels,
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

    def test_review_image_path_is_served_when_present(self):
        self.write_artifact("review.png")

        with patch.object(app, "get_wpt_test", return_value=self.test):
            response = app.test_review_image(self.test.path)

        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.body, b"png")

    def test_diff_serves_cached_runner_artifact(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_artifact("result-vs-reference.png")

        with (
            patch.object(app, "get_wpt_test", return_value=self.test),
            patch.object(app, "image_diff_bytes", side_effect=AssertionError),
        ):
            response = app.test_image(self.test.path, "diff")

        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.body, b"png")

    def test_diff_falls_back_to_generation_without_cached_artifact(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")

        with (
            patch.object(app, "get_wpt_test", return_value=self.test),
            patch.object(app, "image_diff_bytes", return_value=b"generated") as diff,
        ):
            response = app.test_image(self.test.path, "diff")

        diff.assert_called_once_with(b"png", b"png")
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.body, b"generated")

    def test_review_image_link_is_conditional_on_review_artifact(self):
        context = {
            "test": self.test,
            "result_status": "NONE",
            "render_labels": app.RENDER_LABELS,
            "render_availability": {name: False for name in app.RENDER_LABELS},
            "render_name": "olive",
            "render_label": "Olive",
            "render_available": False,
            "image_url": "/test-report/image",
            "review_image_available": False,
            "rejected": False,
            "review_state_available": False,
            "review_status": "pending",
            "review_reason": None,
            "approval_status": "pending",
            "metadata_available": False,
            "olive_available": False,
            "current_result_sha256": None,
            "current_reference_sha256": None,
            "reviewed_result_sha256": None,
            "approved_result_sha256": None,
            "approved_baseline_available": False,
            "current_comparison_available": False,
            "current_diff_percent": None,
            "approved_diff_percent": None,
            "comparison_status": "unavailable",
            "comparison_passed": None,
            "comparison_outcome": "pending",
        }
        template = app.templates.get_template("test-review.html")

        without_review_image = template.render(**context)
        self.assertNotIn(">Review</a>", without_review_image)

        context["review_image_available"] = True
        with_review_image = template.render(**context)
        self.assertIn(f'href="{self.test.review_image_url()}"', with_review_image)

    def test_review_image_endpoint_returns_not_found_when_missing(self):
        with patch.object(app, "get_wpt_test", return_value=self.test):
            with self.assertRaises(app.HTTPException) as error:
                app.test_review_image(self.test.path)

        self.assertEqual(error.exception.status_code, 404)

    def test_review_state_records_reason_and_marks_improved_result_for_review(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(5.0)

        app.write_review_state(self.test, "Text is vertically misaligned")
        rejected = app.report_context(self.test)
        self.assertEqual(rejected["review_status"], "rejected")
        self.assertEqual(rejected["review_reason"], "Text is vertically misaligned")

        (self.artifact_directory / "result.png").write_bytes(b"improved-render")
        self.write_current_comparison(2.0, different_pixels=4)
        improved = app.report_context(self.test)
        self.assertEqual(improved["review_status"], "improved")
        self.assertEqual(app.home_status(self.test), "REVW")

        app.delete_review_state(self.test)
        self.assertFalse(app.review_state_path_for_wpt_path(self.test.path).exists())

    def test_rejected_equal_pixel_diff_remains_failed(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(5.0)

        app.write_review_state(self.test, "Text is still vertically misaligned")
        (self.artifact_directory / "result.png").write_bytes(b"same-diff-render")
        self.write_current_comparison(5.0)

        context = app.report_context(self.test)
        self.assertEqual(context["review_status"], "rejected")
        self.assertEqual(app.home_status(self.test), "FAIL")

    def test_ai_pass_review_state_is_reviewable(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(5.0)
        (self.artifact_directory / "review-state.json").write_text(
            json.dumps(
                {
                    "state": "review",
                    "reason": "The render looks correct.",
                    "olive_result_sha256": app.result_sha256(self.test),
                    "diff_percent": 5.0,
                }
            ),
            encoding="utf-8",
        )

        context = app.report_context(self.test)
        self.assertEqual(context["review_status"], "review")
        self.assertEqual(context["review_reason"], "The render looks correct.")
        self.assertEqual(app.home_status(self.test), "REVW")

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

    def test_approved_improved_render_is_pass_without_review_label(self):
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(0.5)
        current_path = self.artifact_directory / "current.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["run_passed"] = False
        current["run_outcome"] = "pixel_mismatch"
        current_path.write_text(json.dumps(current), encoding="utf-8")
        (self.artifact_directory / "metadata.json").write_text(
            json.dumps(
                {
                    "status": "approved",
                    "approved_result_sha256": "older-render",
                    "approved_diff_percent": 1.0,
                }
            ),
            encoding="utf-8",
        )

        context = app.report_context(self.test)
        self.assertEqual(context["review_status"], "approved")
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
            tests=[{"test": self.test, "status": "NONE", "current_diff_percent": 1.234}],
            status_tabs=app.HOME_STATUS_TABS,
            status_counts={"ALL": 1, "PASS": 0, "FAIL": 0, "REVW": 0, "UNKN": 0, "NONE": 1},
            selected_status="ALL",
        )
        self.assertIn('href="/"', html)
        self.assertIn('href="/?result=none"', html)
        self.assertIn('href="/test-results"', html)
        self.assertNotIn("No tests have this status.", html)
        self.assertIn("Rebuild database", html)
        self.assertIn("(1.23%)", html)

    def test_home_filters_by_prefix_and_result(self):
        css_pass = app.WptTest(
            path="css/pass.html",
            url="https://wpt.live/css/pass.html",
            review_url="/test-report/view?path=css%2Fpass.html",
        )
        js_fail = app.WptTest(
            path="js/fail.html",
            url="https://wpt.live/js/fail.html",
            review_url="/test-report/view?path=js%2Ffail.html",
        )
        items = [
            {"test": self.test, "status": "FAIL", "current_diff_percent": 1.0},
            {"test": css_pass, "status": "PASS", "current_diff_percent": 2.0},
            {"test": js_fail, "status": "FAIL", "current_diff_percent": 3.0},
        ]
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "query_string": b"prefix=css%2F&result=fail",
                "headers": [],
            }
        )

        with patch.object(
            app,
            "load_status_test_items",
            return_value=(
                items,
                {"ALL": 3, "PASS": 1, "FAIL": 2, "REVW": 0, "UNKN": 0, "NONE": 0},
            ),
        ):
            response = app.home(request)

        self.assertEqual(response.context["prefix"], "css/")
        self.assertEqual(response.context["selected_status"], "FAIL")
        self.assertEqual(
            [item["test"].path for item in response.context["tests"]],
            ["css/example.html"],
        )
        self.assertEqual(
            response.context["status_counts"],
            {"ALL": 2, "PASS": 1, "FAIL": 1, "REVW": 0, "UNKN": 0, "NONE": 0},
        )
        self.assertEqual(
            response.context["test_results_url"],
            "/test-results?result=fail&prefix=css%2F",
        )

    def test_pagination_numbers_use_ellipsis_for_large_page_counts(self):
        self.assertEqual(app.pagination_numbers(1, 3), [1, 2, 3])
        self.assertEqual(app.pagination_numbers(1, 10), [1, 2, 3, None, 10])
        self.assertEqual(app.pagination_numbers(5, 10), [1, None, 3, 4, 5, 6, 7, None, 10])
        self.assertEqual(app.pagination_numbers(10, 10), [1, None, 8, 9, 10])

    def test_test_results_page_paginates_to_10_rows(self):
        tests = [
            app.WptTest(
                path=f"css/example-{index}.html",
                url=f"https://wpt.live/css/example-{index}.html",
                review_url=f"/test-report/view?path=css%2Fexample-{index}.html",
            )
            for index in range(26)
        ]
        items = [
            {"test": test, "status": "FAIL", "current_diff_percent": float(index)}
            for index, test in enumerate(tests)
        ]
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/test-results",
                "query_string": b"",
                "headers": [],
            }
        )

        with patch.object(
            app,
            "load_status_test_items",
            return_value=(items, {"ALL": 26, "PASS": 0, "FAIL": 26, "REVW": 0, "UNKN": 0, "NONE": 0}),
        ):
            response = app.test_results(request)

        self.assertEqual(len(response.context["rows"]), 10)
        self.assertEqual(response.context["pagination"]["page"], 1)
        self.assertEqual(response.context["pagination"]["page_count"], 3)
        html = app.templates.get_template("test-results.html").render(**response.context)
        self.assertEqual(html.count('class="test-result-row"'), 10)
        self.assertEqual(html.count('class="test-results-pagination"'), 2)
        self.assertIn('href="/test-results?page=2"', html)

    def test_test_results_page_preserves_result_filter_in_pagination(self):
        tests = [
            app.WptTest(
                path=f"css/fail-{index}.html",
                url=f"https://wpt.live/css/fail-{index}.html",
                review_url=f"/test-report/view?path=css%2Ffail-{index}.html",
            )
            for index in range(26)
        ]
        tests.append(
            app.WptTest(
                path="js/fail.html",
                url="https://wpt.live/js/fail.html",
                review_url="/test-report/view?path=js%2Ffail.html",
            )
        )
        items = [
            {"test": test, "status": "FAIL", "current_diff_percent": None}
            for test in tests
        ]
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/test-results",
                "query_string": b"result=fail&page=2&prefix=css%2F",
                "headers": [],
            }
        )

        with patch.object(
            app,
            "load_status_test_items",
            return_value=(items, {"ALL": 26, "PASS": 0, "FAIL": 26, "REVW": 0, "UNKN": 0, "NONE": 0}),
        ):
            response = app.test_results(request)

        self.assertEqual(response.context["selected_status"], "FAIL")
        self.assertEqual(response.context["prefix"], "css/")
        self.assertEqual(response.context["status_counts"]["ALL"], 26)
        self.assertEqual(len(response.context["rows"]), 10)
        html = app.templates.get_template("test-results.html").render(**response.context)
        self.assertIn(
            'href="/test-results?page=1&amp;result=fail&amp;prefix=css%2F"',
            html,
        )
        self.assertIn('href="/?result=fail&amp;prefix=css%2F"', html)

    def test_test_results_template_has_htmx_image_toggle_and_row_actions(self):
        test = self.test
        self.write_artifact("result.png")
        self.write_artifact("reference.png")
        self.write_current_comparison(2.0)
        row = app.test_result_row(
            {"test": test, "status": "FAIL", "current_diff_percent": 2.0},
            1,
        )
        pagination = {
            "page": 1,
            "page_count": 1,
            "total": 1,
            "numbers": [1],
            "previous_url": None,
            "next_url": None,
            "url": lambda page: f"/test-results?page={page}",
        }
        html = app.templates.get_template("test-results.html").render(
            request=None,
            rows=[row],
            status_counts={"ALL": 1, "PASS": 0, "FAIL": 1, "REVW": 0, "UNKN": 0, "NONE": 0},
            status_tabs=app.HOME_STATUS_TABS,
            selected_status="ALL",
            pagination=pagination,
        )

        self.assertIn('role="group"', html)
        self.assertIn("<table class=\"test-results-table\">", html)
        self.assertIn('hx-target="#test-result-comparison-1"', html)
        self.assertIn('hx-get="/test-results/render?path=css%2Fexample.html&amp;render=diff&amp;target=test-result-comparison-1"', html)
        self.assertIn('hx-get="/test-results/render?path=css%2Fexample.html&amp;render=reference&amp;target=test-result-comparison-1"', html)
        self.assertIn("Result vs Ref", html)
        self.assertIn("[Image]", html)
        self.assertIn("[wpt.live]", html)
        self.assertIn("2.00%", html)
        self.assertNotIn("(2.00%)", html)
        self.assertIn('data-copy-path="css/example.html"', html)
        self.assertIn(">Copy path</button>", html)
        self.assertIn('id="test-result-comparison-1-actions"', html)
        self.assertIn("actions=1", html)
        self.assertIn("padding: 0.25rem 0.5rem", app.STATIC_ROOT.joinpath("css/app.css").read_text())
        self.assertIn('hx-target="closest .approval-controls"', html)
        self.assertIn("hx-vals='{\"reason\":\"Rejected from test results page\"}'", html)
        self.assertNotIn('<textarea', html)

    def test_test_results_render_returns_reference_panel_for_htmx_toggle(self):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/test-results/render",
                "query_string": b"target=test-result-comparison-1",
                "headers": [],
            }
        )

        with patch.object(app, "get_wpt_test", return_value=self.test):
            response = app.test_results_render(request, self.test.path, "reference")

        self.assertIn("Reference", response.body.decode())
        self.assertIn('aria-checked="true"', response.body.decode())
        self.assertIn("test-result-comparison-1", response.body.decode())

    def test_home_tests_sort_by_current_diff_descending_with_missing_last(self):
        lower = app.WptTest(
            path="css/lower.html",
            url="https://wpt.live/css/lower.html",
            review_url="/test-report/view?path=css%2Flower.html",
        )
        higher = app.WptTest(
            path="css/higher.html",
            url="https://wpt.live/css/higher.html",
            review_url="/test-report/view?path=css%2Fhigher.html",
        )
        missing = app.WptTest(
            path="css/missing.html",
            url="https://wpt.live/css/missing.html",
            review_url="/test-report/view?path=css%2Fmissing.html",
        )

        sorted_tests = app.sort_home_tests(
            [
                {"test": lower, "status": "FAIL", "current_diff_percent": 1.0},
                {"test": missing, "status": "NONE", "current_diff_percent": None},
                {"test": higher, "status": "FAIL", "current_diff_percent": 3.0},
            ]
        )

        self.assertEqual([item["test"].path for item in sorted_tests], [
            "css/higher.html",
            "css/lower.html",
            "css/missing.html",
        ])

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
