"""FastAPI application for Olive WPT output review."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
import subprocess
from urllib.parse import parse_qs, quote, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageChops, UnidentifiedImageError

from db import load_test_index, upsert_test


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PROJECT_ROOT / "static"
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
OUTPUTS_ROOT = PROJECT_ROOT / "outputs"
WPT_PATHS_FILE = PROJECT_ROOT / "wpt_paths.txt"
WPT_LIVE_ROOT = "https://wpt.live"
CURRENT_COMPARISON_FILENAME = "current.json"
REVIEW_IMAGE_FILENAME = "review.png"
WPT_DATABASE_FILE = PROJECT_ROOT / "data.sqlite"
REVIEW_STATE_FILENAME = "review-state.json"
RENDER_LABELS = {
    "olive": "Olive render",
    "reference": "Reference",
    "approved-diff": "Result vs Approved",
    "diff": "Result vs Ref",
}
HOME_STATUS_TABS = ("ALL", "PASS", "FAIL", "REVW", "UNKN", "NONE")
TEST_RESULTS_PAGE_SIZE = 25

templates = Jinja2Templates(directory=str(TEMPLATES_ROOT))


@dataclass(frozen=True, slots=True)
class WptTest:
    path: str
    url: str
    review_url: str

    def render_url(self, render_name: str) -> str:
        return f"/test-report/render?{urlencode({'path': self.path, 'render': render_name})}"

    def results_render_url(self, render_name: str, target_id: str) -> str:
        return f"/test-results/render?{urlencode({'path': self.path, 'render': render_name, 'target': target_id})}"

    def asset_url(self, render_name: str) -> str:
        return f"/test-report/image?{urlencode({'path': self.path, 'render': render_name})}"

    def review_image_url(self) -> str:
        return f"/test-report/review-image?{urlencode({'path': self.path})}"

    def approval_url(self, approved: bool, controls_id: str | None = None) -> str:
        endpoint = "approve" if approved else "unapprove"
        query = {"path": self.path}
        if controls_id:
            query["controls_id"] = controls_id
        return f"/test-report/{endpoint}?{urlencode(query)}"

    def rejection_url(self, rejected: bool, controls_id: str | None = None) -> str:
        endpoint = "reject" if rejected else "unreject"
        query = {"path": self.path}
        if controls_id:
            query["controls_id"] = controls_id
        return f"/test-report/{endpoint}?{urlencode(query)}"


def load_wpt_paths(path: Path = WPT_PATHS_FILE) -> tuple[str, ...]:
    """Read the curated WPT inventory without inspecting Git or output files."""

    paths: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = line.split("#", 1)[0].strip()
        if not value:
            continue

        candidate = PurePosixPath(value)
        if (
            candidate.is_absolute()
            or "\\" in value
            or candidate == PurePosixPath(".")
            or ".." in candidate.parts
        ):
            raise ValueError(
                f"WPT path on line {line_number} must be a safe relative path: {value}"
            )

        normalized = candidate.as_posix()
        if normalized in seen:
            raise ValueError(f"duplicate WPT path on line {line_number}: {normalized}")
        seen.add(normalized)
        paths.append(normalized)

    if not paths:
        raise ValueError(f"WPT path list is empty: {path}")
    return tuple(sorted(paths))


def load_wpt_tests() -> tuple[WptTest, ...]:
    return tuple(
        WptTest(
            path=path,
            url=f"{WPT_LIVE_ROOT}/{quote(path, safe='/')}",
            review_url=f"/test-report/view?{urlencode({'path': path})}",
        )
        for path in load_wpt_paths()
    )


def output_directory_for_wpt_path(wpt_path: str) -> Path:
    source_path = PurePosixPath(wpt_path)
    suffix = source_path.suffix.removeprefix(".")
    stem = source_path.name[: -(len(suffix) + 1)] if suffix else source_path.name
    output_name = f"{stem}-{suffix}-test" if suffix else f"{stem}-test"
    return OUTPUTS_ROOT.joinpath(*source_path.parts[:-1], output_name)


def metadata_path_for_wpt_path(wpt_path: str) -> Path:
    return output_directory_for_wpt_path(wpt_path) / "metadata.json"


def review_state_path_for_wpt_path(wpt_path: str) -> Path:
    return output_directory_for_wpt_path(wpt_path) / REVIEW_STATE_FILENAME


def review_image_path_for_wpt_path(wpt_path: str) -> Path:
    return output_directory_for_wpt_path(wpt_path) / REVIEW_IMAGE_FILENAME


def current_comparison_path_for_wpt_path(wpt_path: str) -> Path:
    return output_directory_for_wpt_path(wpt_path) / CURRENT_COMPARISON_FILENAME


def load_metadata(test: WptTest) -> dict[str, object] | None:
    metadata_path = metadata_path_for_wpt_path(test.path)
    if not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Test metadata is invalid JSON") from error
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="Test metadata must be a JSON object")
    return metadata


def load_current_comparison(test: WptTest) -> dict[str, object] | None:
    current_path = current_comparison_path_for_wpt_path(test.path)
    if not current_path.is_file():
        return None
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Current comparison is invalid JSON") from error
    if not isinstance(current, dict):
        raise HTTPException(status_code=500, detail="Current comparison must be a JSON object")
    return current


def load_review_state(test: WptTest) -> dict[str, object] | None:
    review_path = review_state_path_for_wpt_path(test.path)
    if not review_path.is_file():
        return None
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail="Review state is invalid JSON") from error
    if not isinstance(review, dict):
        raise HTTPException(status_code=500, detail="Review state must be a JSON object")
    return review


def result_sha256(test: WptTest) -> str | None:
    result_path = output_directory_for_wpt_path(test.path) / "result.png"
    if not result_path.is_file():
        return None
    return hashlib.sha256(result_path.read_bytes()).hexdigest()


def reference_sha256(test: WptTest) -> str | None:
    reference_path = output_directory_for_wpt_path(test.path) / "reference.png"
    if not reference_path.is_file():
        return None
    return hashlib.sha256(reference_path.read_bytes()).hexdigest()


def write_review_state(test: WptTest, reason: str) -> None:
    current = load_current_comparison(test)
    result_hash = result_sha256(test)
    if result_hash is None:
        raise HTTPException(status_code=409, detail="Current Olive render is not available")
    state = {
        "schema_version": 1,
        "state": "rejected",
        "reason": reason,
        "olive_result_sha256": result_hash,
        "reference_sha256": reference_sha256(test),
        "diff_percent": comparison_number(current, "current_diff_percent"),
        "different_pixels": comparison_number(current, "current_different_pixels"),
        "total_pixels": comparison_number(current, "current_total_pixels"),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    review_path = review_state_path_for_wpt_path(test.path)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = review_path.with_name(f".{review_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(review_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def delete_review_state(test: WptTest) -> None:
    try:
        review_state_path_for_wpt_path(test.path).unlink()
    except FileNotFoundError:
        pass


def approved_result_bytes(test: WptTest) -> bytes | None:
    metadata = load_metadata(test)
    if metadata is None or metadata.get("status") != "approved":
        return None
    relative_path = output_directory_for_wpt_path(test.path).relative_to(PROJECT_ROOT)
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{relative_path.as_posix()}/result.png"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def image_diff_bytes(left: bytes, right: bytes) -> bytes:
    try:
        left_image = Image.open(BytesIO(left)).convert("RGBA")
        right_image = Image.open(BytesIO(right)).convert("RGBA")
    except UnidentifiedImageError as error:
        raise HTTPException(status_code=500, detail="Render image is invalid") from error
    width = max(left_image.width, right_image.width)
    height = max(left_image.height, right_image.height)
    if left_image.size != (width, height):
        canvas = Image.new("RGBA", (width, height))
        canvas.paste(left_image, (0, 0))
        left_image = canvas
    if right_image.size != (width, height):
        canvas = Image.new("RGBA", (width, height))
        canvas.paste(right_image, (0, 0))
        right_image = canvas
    difference = ImageChops.difference(left_image.convert("RGB"), right_image.convert("RGB"))
    mask = difference.convert("L").point(lambda value: 255 if value else 0)
    diff = Image.new("RGBA", (width, height), (255, 0, 0, 0))
    diff.putalpha(mask)
    output = BytesIO()
    diff.save(output, format="PNG")
    return output.getvalue()


def comparison_number(comparison: dict[str, object] | None, key: str) -> float | None:
    if comparison is None:
        return None
    value = comparison.get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def review_delta_status(
    current_hash: str | None,
    current_diff_percent: float | None,
    current_different_pixels: float | None,
    reviewed_hash: str | None,
    reviewed_diff_percent: float | None,
    reviewed_different_pixels: float | None,
    same_result_label: str,
) -> str:
    if current_hash and reviewed_hash and current_hash == reviewed_hash:
        return same_result_label
    if current_different_pixels is not None and reviewed_different_pixels is not None:
        if current_different_pixels < reviewed_different_pixels:
            return "improved"
        if current_different_pixels > reviewed_different_pixels:
            return "regressed"
        if same_result_label == "rejected":
            return same_result_label
    if current_diff_percent is not None and reviewed_diff_percent is not None:
        if current_diff_percent < reviewed_diff_percent:
            return "improved"
        if current_diff_percent > reviewed_diff_percent:
            return "regressed"
        if same_result_label == "rejected":
            return same_result_label
    return "changed"


def report_context(test: WptTest) -> dict[str, object]:
    metadata = load_metadata(test)
    current = load_current_comparison(test)
    review_state = load_review_state(test)
    output_directory = output_directory_for_wpt_path(test.path)
    current_diff_percent = comparison_number(current, "current_diff_percent")
    run_passed = current.get("run_passed") if current and isinstance(current.get("run_passed"), bool) else None
    run_outcome = current.get("run_outcome") if current and isinstance(current.get("run_outcome"), str) else None
    run_detail = current.get("run_detail") if current and isinstance(current.get("run_detail"), str) else None
    approved_diff_percent = comparison_number(metadata, "approved_diff_percent")
    current_different_pixels = comparison_number(current, "current_different_pixels")
    current_hash = result_sha256(test)
    current_reference_hash = reference_sha256(test)
    approved_hash = metadata.get("approved_result_sha256") if metadata else None
    reviewed_hash = review_state.get("olive_result_sha256") if review_state else None
    reviewed_diff_percent = comparison_number(review_state, "diff_percent")
    reviewed_different_pixels = comparison_number(review_state, "different_pixels")
    comparison_status = "unavailable"
    comparison_passed: bool | None = None
    if current_diff_percent is not None and approved_diff_percent is not None:
        if current_hash and current_hash == approved_hash:
            comparison_status = "unchanged"
            comparison_passed = True
        elif current_diff_percent < approved_diff_percent:
            comparison_status = "improved"
            comparison_passed = True
        elif current_diff_percent == approved_diff_percent:
            comparison_status = "equal"
            comparison_passed = True
        else:
            comparison_status = "regressed"
            comparison_passed = False
    elif current_diff_percent is not None:
        comparison_status = "awaiting approval"
    if review_state is not None:
        review_label = "rejected" if review_state.get("state") == "rejected" else "review"
        review_status = review_delta_status(
            current_hash,
            current_diff_percent,
            current_different_pixels,
            reviewed_hash if isinstance(reviewed_hash, str) else None,
            reviewed_diff_percent,
            reviewed_different_pixels,
            review_label,
        )
    elif metadata and metadata.get("status") == "approved":
        review_status = review_delta_status(
            current_hash,
            current_diff_percent,
            current_different_pixels,
            approved_hash if isinstance(approved_hash, str) else None,
            approved_diff_percent,
            comparison_number(metadata, "approved_different_pixels"),
            "approved",
        )
        if review_status == "improved":
            review_status = "approved"
    else:
        review_status = "pending"
    return {
        "rejected": review_status == "rejected",
        "review_state_available": review_state is not None,
        "review_status": review_status,
        "review_reason": review_state.get("reason") if review_state else None,
        "review_model": review_state.get("review_model") if review_state else None,
        "review_result": review_state.get("review_result") if review_state else None,
        "approval_status": "approved" if metadata and metadata.get("status") == "approved" else "pending",
        "metadata_available": metadata is not None,
        "olive_available": (output_directory / "result.png").is_file(),
        "current_result_sha256": current_hash,
        "current_reference_sha256": current_reference_hash,
        "reviewed_result_sha256": reviewed_hash,
        "approved_result_sha256": approved_hash,
        "approved_baseline_available": approved_hash is not None and approved_diff_percent is not None,
        "current_comparison_available": current_diff_percent is not None,
        "current_diff_percent": current_diff_percent,
        "run_passed": run_passed,
        "run_outcome": run_outcome,
        "run_detail": run_detail,
        "approved_diff_percent": approved_diff_percent,
        "comparison_status": comparison_status,
        "comparison_passed": comparison_passed,
        "comparison_outcome": (
            "pass" if comparison_passed is True else "fail" if comparison_passed is False else "pending"
        ),
    }


def home_status(test: WptTest) -> str:
    context = report_context(test)
    if not context["olive_available"]:
        return "NONE"
    if context["review_status"] == "review":
        return "REVW"
    approved_improved = (
        context["approval_status"] == "approved"
        and not context["review_state_available"]
        and context["current_diff_percent"] is not None
        and context["approved_diff_percent"] is not None
        and context["current_diff_percent"] < context["approved_diff_percent"]
    )
    if context["run_passed"] is False:
        approved_hash = context["approved_result_sha256"]
        current_hash = context["current_result_sha256"]
        if not (
            context["approval_status"] == "approved"
            and (
                (current_hash and current_hash == approved_hash)
                or approved_improved
            )
        ):
            return "FAIL"
    if context["review_status"] == "rejected":
        return "FAIL"
    if context["review_status"] in {"changed", "improved", "regressed"}:
        return "REVW"
    if context["approval_status"] != "approved" or not context["approved_baseline_available"]:
        return "UNKN"
    current_hash = context["current_result_sha256"]
    approved_hash = context["approved_result_sha256"]
    if not current_hash or not approved_hash:
        return "UNKN"
    return "PASS" if current_hash == approved_hash or approved_improved else "REVW"


def load_database_test_index() -> dict[str, dict[str, object]]:
    try:
        return load_test_index(WPT_DATABASE_FILE)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="WPT database is missing; run wpt-outputs/bin/build-db",
        ) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="WPT database is unavailable") from error


def update_database_test(test: WptTest) -> None:
    try:
        upsert_test(PROJECT_ROOT, test.path, home_status(test))
    except Exception as error:
        raise HTTPException(status_code=500, detail="Could not update WPT database") from error


def stage_test_output(test: WptTest) -> None:
    try:
        output_directory = output_directory_for_wpt_path(test.path).relative_to(PROJECT_ROOT)
        subprocess.run(
            ["git", "add", "--all", "--", output_directory.as_posix()],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise HTTPException(status_code=500, detail="Could not stage approved WPT output") from error


def result_status(test: WptTest) -> str:
    return home_status(test)


def render_context(test: WptTest, render_name: str) -> dict[str, object]:
    try:
        render_label = RENDER_LABELS[render_name]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown render") from error
    directory = output_directory_for_wpt_path(test.path)
    result_available = (directory / "result.png").is_file()
    reference_available = (directory / "reference.png").is_file()
    if render_name == "olive":
        render_available = result_available
    elif render_name == "reference":
        render_available = reference_available
    elif render_name == "diff":
        render_available = result_available and reference_available
    else:
        render_available = False
    if render_name == "approved-diff":
        render_available = result_available and approved_result_bytes(test) is not None
    return {
        "test": test,
        "render_label": render_label,
        "render_name": render_name,
        "render_available": render_available,
        "image_url": test.asset_url(render_name),
    }


def render_availability(test: WptTest) -> dict[str, bool]:
    return {
        name: bool(render_context(test, name)["render_available"])
        for name in RENDER_LABELS
    }


def render_image_bytes(test: WptTest, render_name: str) -> bytes | None:
    directory = output_directory_for_wpt_path(test.path)
    if render_name == "approved-diff":
        current_path = directory / "result.png"
        approved = approved_result_bytes(test)
        if not current_path.is_file() or approved is None:
            return None
        return image_diff_bytes(current_path.read_bytes(), approved)
    if render_name == "diff":
        result_path = directory / "result.png"
        reference_path = directory / "reference.png"
        if not result_path.is_file() or not reference_path.is_file():
            return None
        return image_diff_bytes(result_path.read_bytes(), reference_path.read_bytes())
    asset_name = {"olive": "result.png", "reference": "reference.png"}.get(render_name)
    if asset_name is None:
        return None
    asset = directory / asset_name
    return asset.read_bytes() if asset.is_file() else None


def write_approval_status(test: WptTest, status: str) -> None:
    metadata_path = metadata_path_for_wpt_path(test.path)
    metadata = load_metadata(test)
    if metadata is None:
        if status != "approved":
            raise HTTPException(status_code=404, detail="Test metadata not found")
        metadata = new_metadata(test)
    if status == "approved":
        current = load_current_comparison(test)
        current_diff_percent = comparison_number(current, "current_diff_percent")
        current_different_pixels = comparison_number(current, "current_different_pixels")
        current_total_pixels = comparison_number(current, "current_total_pixels")
        current_hash = result_sha256(test)
        if current_diff_percent is None or current_hash is None:
            raise HTTPException(status_code=409, detail="Current comparison is not available")
        metadata["approved_result_sha256"] = current_hash
        metadata["approved_diff_percent"] = current_diff_percent
        if current_different_pixels is not None:
            metadata["approved_different_pixels"] = int(current_different_pixels)
        if current_total_pixels is not None:
            metadata["approved_total_pixels"] = int(current_total_pixels)

    metadata["status"] = status
    temporary_path = metadata_path.with_name(f".{metadata_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(metadata_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def new_metadata(test: WptTest) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "pending",
        "olive_version": olive_version(),
        "reference_browser": "chromium",
        "reference_browser_version": reference_browser_version(),
        "wpt_url": test.url,
        "wpt_local_path": test.path,
    }


def olive_version() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "0.1.0+unknown"
    revision = result.stdout.strip()
    return f"0.1.0+{revision}" if revision else "0.1.0+unknown"


def reference_browser_version() -> str:
    report_path = PROJECT_ROOT / "current" / "reference-generation.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    version = report.get("chromium_version")
    return version if isinstance(version, str) and version else "unknown"


def run_build_db() -> None:
    try:
        subprocess.run(
            [str(PROJECT_ROOT / "bin" / "build-db")],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise HTTPException(status_code=500, detail="Could not rebuild WPT database") from error


def get_wpt_test(wpt_path: str) -> WptTest:
    test = next((test for test in load_wpt_tests() if test.path == wpt_path), None)
    if test is None:
        raise HTTPException(status_code=404, detail="WPT test not found")
    return test


def sort_home_tests(tests: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        tests,
        key=lambda item: (
            item["current_diff_percent"] is None,
            -(item["current_diff_percent"] or 0.0),
            item["test"].path,
        ),
    )


def selected_status_from_request(request: Request) -> str:
    selected_result = request.query_params.get("result")
    if selected_result is None or not selected_result.strip():
        return "ALL"
    selected_status = selected_result.strip().upper()
    if selected_status not in HOME_STATUS_TABS[1:]:
        raise HTTPException(
            status_code=400,
            detail="result must be one of unkn, fail, pass, revw, or none",
        )
    return selected_status


def load_status_test_items() -> tuple[list[dict[str, object]], dict[str, int]]:
    wpt_tests = load_wpt_tests()
    test_index = load_database_test_index()
    all_tests = sort_home_tests(
        [
            {
                "test": test,
                "status": test_index.get(test.path, {}).get("status", "NONE"),
                "current_diff_percent": test_index.get(test.path, {}).get(
                    "current_diff_percent"
                ),
            }
            for test in wpt_tests
        ]
    )
    status_counts = {status: 0 for status in HOME_STATUS_TABS}
    status_counts["ALL"] = len(all_tests)
    for item in all_tests:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    return all_tests, status_counts


def parse_page(request: Request) -> int:
    raw_page = request.query_params.get("page", "1")
    try:
        page = int(raw_page)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="page must be a positive integer") from error
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be a positive integer")
    return page


def pagination_numbers(current_page: int, page_count: int) -> list[int | None]:
    if page_count <= 7:
        return list(range(1, page_count + 1))
    pages: list[int | None] = [1]
    start = max(2, current_page - 2)
    end = min(page_count - 1, current_page + 2)
    if start > 2:
        pages.append(None)
    pages.extend(range(start, end + 1))
    if end < page_count - 1:
        pages.append(None)
    pages.append(page_count)
    return pages


def test_results_page_url(page: int, selected_status: str) -> str:
    query = {"page": page}
    if selected_status != "ALL":
        query["result"] = selected_status.lower()
    return f"/test-results?{urlencode(query)}"


def test_result_row(
    item: dict[str, object],
    row_number: int,
) -> dict[str, object]:
    test = item["test"]
    assert isinstance(test, WptTest)
    return {
        "test": test,
        "status": item["status"],
        "result_status": item["status"],
        "current_diff_percent": item["current_diff_percent"],
        "row_number": row_number,
        "render_target": f"test-result-render-{row_number}",
        "comparison_panel_id": f"test-result-comparison-{row_number}",
        "controls_id": f"test-result-controls-{row_number}",
        "feedback_id": f"test-result-feedback-{row_number}",
        "rejection_reason_id": f"test-result-rejection-reason-{row_number}",
        "compact_review": True,
        "olive_render": render_context(test, "olive"),
        "comparison_render": render_context(test, "diff"),
        "reference_render": render_context(test, "reference"),
        **report_context(test),
    }


app = FastAPI(
    title="Olive WPT Output Review",
    version="0.1.0",
    description="Review approved and current Olive WPT rendering output.",
)

app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    all_tests, status_counts = load_status_test_items()
    selected_status = selected_status_from_request(request)
    tests = (
        all_tests
        if selected_status == "ALL"
        else [item for item in all_tests if item["status"] == selected_status]
    )
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "tests": tests,
            "status_counts": status_counts,
            "status_tabs": HOME_STATUS_TABS,
            "selected_status": selected_status,
        },
    )


@app.get("/test-results", response_class=HTMLResponse)
def test_results(request: Request) -> HTMLResponse:
    all_tests, status_counts = load_status_test_items()
    selected_status = selected_status_from_request(request)
    filtered_tests = (
        all_tests
        if selected_status == "ALL"
        else [item for item in all_tests if item["status"] == selected_status]
    )

    total = len(filtered_tests)
    page_count = max(1, (total + TEST_RESULTS_PAGE_SIZE - 1) // TEST_RESULTS_PAGE_SIZE)
    requested_page = parse_page(request)
    page = min(requested_page, page_count)
    offset = (page - 1) * TEST_RESULTS_PAGE_SIZE
    page_items = filtered_tests[offset : offset + TEST_RESULTS_PAGE_SIZE]
    rows = [
        test_result_row(item, offset + index + 1)
        for index, item in enumerate(page_items)
    ]
    pagination = {
        "page": page,
        "page_count": page_count,
        "total": total,
        "numbers": pagination_numbers(page, page_count),
        "previous_url": test_results_page_url(page - 1, selected_status) if page > 1 else None,
        "next_url": test_results_page_url(page + 1, selected_status)
        if page < page_count
        else None,
        "url": lambda page_number: test_results_page_url(page_number, selected_status),
    }
    return templates.TemplateResponse(
        request=request,
        name="test-results.html",
        context={
            "rows": rows,
            "status_counts": status_counts,
            "status_tabs": HOME_STATUS_TABS,
            "selected_status": selected_status,
            "pagination": pagination,
        },
    )


@app.get("/test-results/render", response_class=HTMLResponse)
def test_results_render(request: Request, path: str, render: str = "diff") -> HTMLResponse:
    test = get_wpt_test(path)
    if render not in {"diff", "reference"}:
        raise HTTPException(status_code=404, detail="Unknown test result render")
    target_id = request.query_params.get("target", "test-result-comparison")
    if not target_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid comparison target")
    return templates.TemplateResponse(
        request=request,
        name="test-results-comparison.html",
        context={
            "test": test,
            "render_name": render,
            "render_context": render_context(test, render),
            "reference_context": render_context(test, "reference"),
            "diff_context": render_context(test, "diff"),
            "comparison_panel_id": target_id,
        },
    )


@app.get("/test-report/view", response_class=HTMLResponse)
def test_review(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    return templates.TemplateResponse(
        request=request,
        name="test-review.html",
        context={
            "test": test,
            "result_status": result_status(test),
            "render_labels": RENDER_LABELS,
            "render_availability": render_availability(test),
            "review_image_available": review_image_path_for_wpt_path(test.path).is_file(),
            **report_context(test),
            **render_context(test, "olive"),
        },
    )


@app.get("/test-report/render", response_class=HTMLResponse)
def test_render(request: Request, path: str, render: str = "olive") -> HTMLResponse:
    test = get_wpt_test(path)
    return templates.TemplateResponse(
        request=request,
        name="render-panel.html",
        context=render_context(test, render),
    )


@app.get("/test-report/image")
def test_image(path: str, render: str = "olive") -> Response:
    test = get_wpt_test(path)
    render_context(test, render)
    image = render_image_bytes(test, render)
    if image is None:
        raise HTTPException(status_code=404, detail="Test asset not found")
    return Response(content=image, media_type="image/png")


@app.get("/test-report/review-image")
def test_review_image(path: str) -> Response:
    test = get_wpt_test(path)
    review_image = review_image_path_for_wpt_path(test.path)
    if not review_image.is_file():
        raise HTTPException(status_code=404, detail="Review image not found")
    return Response(content=review_image.read_bytes(), media_type="image/png")


def approval_response(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    controls_id = request.query_params.get("controls_id")
    feedback_id = f"{controls_id}-feedback" if controls_id else None
    rejection_reason_id = f"{controls_id}-rejection-reason" if controls_id else None
    return templates.TemplateResponse(
        request=request,
        name="approval-controls.html",
        context={
            "test": test,
            "result_status": result_status(test),
            "feedback_id": feedback_id,
            "rejection_reason_id": rejection_reason_id,
            "controls_id": controls_id,
            **report_context(test),
        },
    )


@app.post("/test-report/approve", response_class=HTMLResponse)
def approve_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    write_approval_status(test, "approved")
    delete_review_state(test)
    update_database_test(test)
    stage_test_output(test)
    return approval_response(request, path)


@app.post("/test-report/unapprove", response_class=HTMLResponse)
def unapprove_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    write_approval_status(test, "pending")
    update_database_test(test)
    return approval_response(request, path)


@app.post("/test-report/reject", response_class=HTMLResponse)
async def reject_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    if not result_sha256(test):
        raise HTTPException(status_code=409, detail="Current Olive render is not available")
    body = parse_qs((await request.body()).decode("utf-8"))
    reason = body.get("reason", [""])[0].strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A rejection reason is required")
    write_review_state(test, reason)
    update_database_test(test)
    return approval_response(request, path)


@app.post("/test-report/unreject", response_class=HTMLResponse)
def unreject_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    delete_review_state(test)
    update_database_test(test)
    return approval_response(request, path)


@app.post("/test-report/reconcile", status_code=204)
def reconcile_results() -> Response:
    run_build_db()
    return Response(status_code=204)


__all__ = ["app"]
