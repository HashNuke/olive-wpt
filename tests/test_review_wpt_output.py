import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "bin" / "review-wpt-output"
SPEC = importlib.util.spec_from_loader(
    "review_wpt_output",
    SourceFileLoader("review_wpt_output", str(SCRIPT_PATH)),
)
review_wpt_output = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(review_wpt_output)


class ReviewWptOutputTests(unittest.TestCase):
    def test_output_directory_round_trips_to_wpt_path(self):
        output_directory = (
            review_wpt_output.OUTPUTS_ROOT
            / "css"
            / "css-backgrounds"
            / "background-image-001-html-test"
        )

        self.assertEqual(
            review_wpt_output.wpt_path_for_output_directory(output_directory),
            "css/css-backgrounds/background-image-001.html",
        )

    def test_response_text_collects_candidate_parts(self):
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "The Olive render is missing the red box."},
                            {"text": "The green box is also shifted."},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(
            review_wpt_output.response_text(response),
            "The Olive render is missing the red box.\n\nThe green box is also shifted.",
        )

    def test_response_text_ignores_thought_parts(self):
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Internal reasoning."},
                            {"text": "Visible feedback."},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(review_wpt_output.response_text(response), "Visible feedback.")

    def test_format_review_output_includes_path_and_feedback(self):
        self.assertEqual(
            review_wpt_output.format_review_output(
                Path("outputs/css/example-html-test/review-state.json"),
                "The Olive render is missing the red box.",
            ),
            "Review JSON path: outputs/css/example-html-test/review-state.json\n\n"
            "------REVIEW------\n\n"
            "The Olive render is missing the red box.",
        )

    def test_generate_feedback_sends_inline_prompt_and_image(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "review.png"
            image_path.write_bytes(b"png-bytes")
            response = {
                "candidates": [{"content": {"parts": [{"text": "Feedback"}]}}]
            }

            with patch.object(review_wpt_output, "api_request", return_value=response) as request:
                feedback = review_wpt_output.generate_feedback(
                    "test-key", "gemini-3.5-flash-lite", image_path
                )

            self.assertEqual(feedback, "Feedback")
            payload = request.call_args.args[2]
            self.assertNotIn("cachedContent", payload)
            self.assertEqual(payload["contents"][0]["parts"][0]["text"], review_wpt_output.PROMPT)
            self.assertEqual(
                payload["contents"][0]["parts"][1]["inline_data"]["mime_type"],
                "image/png",
            )

    def test_write_review_state_stores_gemini_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            (output_directory / "result.png").write_bytes(b"result")
            (output_directory / "reference.png").write_bytes(b"reference")
            (output_directory / "review.png").write_bytes(b"review")
            (output_directory / "current.json").write_text(
                json.dumps(
                    {
                        "current_diff_percent": 3.0,
                        "current_different_pixels": 12,
                        "current_total_pixels": 100,
                    }
                ),
                encoding="utf-8",
            )

            review_path = review_wpt_output.write_review_state(
                "css/example.html",
                output_directory,
                "The Olive render is missing the red box.",
                output_directory / "review.png",
                "gemini-3.5-flash-lite",
            )
            state = json.loads(review_path.read_text(encoding="utf-8"))

            self.assertEqual(state["state"], "rejected")
            self.assertEqual(state["reason"], "The Olive render is missing the red box.")
            self.assertEqual(state["gemini_feedback"], state["reason"])
            self.assertEqual(state["gemini_review"]["model"], "gemini-3.5-flash-lite")
            self.assertNotIn("prompt_cached", state["gemini_review"])
            self.assertEqual(state["different_pixels"], 12)


if __name__ == "__main__":
    unittest.main()
