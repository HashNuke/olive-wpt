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

    def test_build_prompt_includes_both_diff_percentages_and_json_contract(self):
        prompt = review_wpt_output.build_prompt(1.25, 2.5)
        self.assertIn("approved image diff percentage is: 1.2500%", prompt)
        self.assertIn("current image diff percentage is: 2.5000%", prompt)
        self.assertIn('"result": "PASS" or "FAIL"', prompt)

    def test_parse_review_response_requires_pass_or_fail_json(self):
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '```json\n{"result":"PASS","feedback":"Looks correct."}\n```'
                            }
                        ]
                    }
                }
            ]
        }
        self.assertEqual(
            review_wpt_output.parse_review_response(response),
            ("PASS", "Looks correct."),
        )

        response["candidates"][0]["content"]["parts"][0]["text"] = (
            '{"result":"MAYBE","feedback":"Unclear."}'
        )
        with self.assertRaises(review_wpt_output.GeminiApiError):
            review_wpt_output.parse_review_response(response)

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
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"result":"PASS","feedback":"Feedback"}'
                                }
                            ]
                        }
                    }
                ]
            }

            with patch.object(review_wpt_output, "api_request", return_value=response) as request:
                result, feedback = review_wpt_output.generate_review(
                    "test-key", "gemini-3.5-flash-lite", image_path, "Review prompt"
                )

            self.assertEqual(result, "PASS")
            self.assertEqual(feedback, "Feedback")
            payload = request.call_args.args[2]
            self.assertNotIn("cachedContent", payload)
            self.assertEqual(payload["contents"][0]["parts"][0]["text"], "Review prompt")
            self.assertEqual(
                payload["contents"][0]["parts"][1]["inline_data"]["mime_type"],
                "image/png",
            )

    def test_write_review_state_uses_human_review_fields(self):
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
                "PASS",
                "The Olive render is missing the red box.",
                output_directory / "review.png",
                "gemini-3.5-flash-lite",
                "Review prompt",
                1.5,
            )
            state = json.loads(review_path.read_text(encoding="utf-8"))

            self.assertEqual(state["state"], "review")
            self.assertEqual(state["reason"], "The Olive render is missing the red box.")
            self.assertEqual(state["review_model"], "gemini-3.5-flash-lite")
            self.assertEqual(state["review_result"], "PASS")
            self.assertEqual(state["approved_diff_percent"], 1.5)
            self.assertNotIn("ai_feedback", state)
            self.assertNotIn("gemini_feedback", state)
            self.assertNotIn("gemini_review", state)
            self.assertEqual(state["different_pixels"], 12)

    def test_write_review_state_maps_fail_to_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            (output_directory / "result.png").write_bytes(b"result")
            (output_directory / "reference.png").write_bytes(b"reference")
            (output_directory / "review.png").write_bytes(b"review")

            review_path = review_wpt_output.write_review_state(
                "css/example.html",
                output_directory,
                "FAIL",
                "The Olive render is wrong.",
                output_directory / "review.png",
                "gemini-3.5-flash-lite",
                "Review prompt",
                None,
            )

            state = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"], "rejected")
            self.assertEqual(state["reason"], "The Olive render is wrong.")

    def test_ai_pass_fail_states_cover_approved_and_unapproved_renders(self):
        for has_approved_render in (False, True):
            for review_result, expected_state in (("PASS", "review"), ("FAIL", "rejected")):
                with self.subTest(
                    has_approved_render=has_approved_render,
                    review_result=review_result,
                ), tempfile.TemporaryDirectory() as directory:
                    output_directory = Path(directory)
                    (output_directory / "result.png").write_bytes(b"result")
                    (output_directory / "reference.png").write_bytes(b"reference")
                    if has_approved_render:
                        (output_directory / "metadata.json").write_text(
                            json.dumps(
                                {
                                    "status": "approved",
                                    "approved_diff_percent": 1.0,
                                }
                            ),
                            encoding="utf-8",
                        )

                    review_path = review_wpt_output.write_review_state(
                        "css/example.html",
                        output_directory,
                        review_result,
                        "Review feedback",
                        output_directory / "review.png",
                        "gemini-3.5-flash-lite",
                        review_wpt_output.build_prompt(
                            1.0 if has_approved_render else None,
                            2.0,
                        ),
                        1.0 if has_approved_render else None,
                    )

                    state = json.loads(review_path.read_text(encoding="utf-8"))
                    self.assertEqual(state["state"], expected_state)
                    self.assertEqual(
                        state["approved_diff_percent"],
                        1.0 if has_approved_render else None,
                    )


if __name__ == "__main__":
    unittest.main()
