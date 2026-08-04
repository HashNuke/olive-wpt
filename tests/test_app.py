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


if __name__ == "__main__":
    unittest.main()
