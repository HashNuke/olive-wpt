"""FastAPI application for Olive WPT output review."""

import csv
import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
import subprocess
from urllib.parse import quote, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageChops, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PROJECT_ROOT / "static"
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
OUTPUTS_ROOT = PROJECT_ROOT / "outputs"
WPT_PATHS_FILE = PROJECT_ROOT / "wpt_paths.txt"
WPT_LIVE_ROOT = "https://wpt.live"
CURRENT_COMPARISON_FILENAME = "current.json"
WPT_RESULTS_FILE = PROJECT_ROOT / "current" / "result.csv"
RENDER_LABELS = {
    "olive": "Olive render",
    "reference": "Reference",
    "approved-diff": "Result vs Approved",
    "diff": "Result vs Ref",
}

templates = Jinja2Templates(directory=str(TEMPLATES_ROOT))


@dataclass(frozen=True, slots=True)
class WptTest:
    path: str
    url: str
    review_url: str

    def render_url(self, render_name: str) -> str:
        return f"/test-report/render?{urlencode({'path': self.path, 'render': render_name})}"

    def asset_url(self, render_name: str) -> str:
        return f"/test-report/image?{urlencode({'path': self.path, 'render': render_name})}"

    def approval_url(self, approved: bool) -> str:
        endpoint = "approve" if approved else "unapprove"
        return f"/test-report/{endpoint}?{urlencode({'path': self.path})}"


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


def result_sha256(test: WptTest) -> str | None:
    result_path = output_directory_for_wpt_path(test.path) / "result.png"
    if not result_path.is_file():
        return None
    return hashlib.sha256(result_path.read_bytes()).hexdigest()


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


def report_context(test: WptTest) -> dict[str, object]:
    metadata = load_metadata(test)
    current = load_current_comparison(test)
    output_directory = output_directory_for_wpt_path(test.path)
    current_diff_percent = comparison_number(current, "current_diff_percent")
    approved_diff_percent = comparison_number(metadata, "approved_diff_percent")
    current_hash = result_sha256(test)
    approved_hash = metadata.get("approved_result_sha256") if metadata else None
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
    return {
        "approval_status": "approved" if metadata and metadata.get("status") == "approved" else "pending",
        "metadata_available": metadata is not None,
        "olive_available": (output_directory / "result.png").is_file(),
        "current_result_sha256": current_hash,
        "approved_result_sha256": approved_hash,
        "approved_baseline_available": approved_hash is not None and approved_diff_percent is not None,
        "current_comparison_available": current_diff_percent is not None,
        "current_diff_percent": current_diff_percent,
        "approved_diff_percent": approved_diff_percent,
        "comparison_status": comparison_status,
        "comparison_passed": comparison_passed,
        "comparison_outcome": (
            "pass" if comparison_passed is True else "fail" if comparison_passed is False else "pending"
        ),
    }


def home_status(test: WptTest) -> str:
    context = report_context(test)
    if context["approval_status"] != "approved" or not context["approved_baseline_available"]:
        return "UNKN"
    current_hash = context["current_result_sha256"]
    approved_hash = context["approved_result_sha256"]
    if not current_hash or not approved_hash:
        return "UNKN"
    return "PASS" if current_hash == approved_hash else "FAIL"


def load_result_statuses(path: Path = WPT_RESULTS_FILE) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = csv.DictReader(handle)
            if rows.fieldnames != ["status", "path"]:
                raise ValueError("result CSV must have status,path columns")
            statuses: dict[str, str] = {}
            for row in rows:
                status = row.get("status")
                wpt_path = row.get("path")
                if status not in {"PASS", "FAIL", "UNKN"} or not wpt_path:
                    raise ValueError("result CSV contains an invalid row")
                statuses[wpt_path] = status
            return statuses
    except (OSError, csv.Error, ValueError) as error:
        raise HTTPException(status_code=500, detail="WPT result CSV is invalid") from error


def write_result_statuses(tests: tuple[WptTest, ...]) -> None:
    WPT_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = WPT_RESULTS_FILE.with_name(f".{WPT_RESULTS_FILE.name}.tmp")
    try:
        with temporary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("status", "path"))
            for test in tests:
                writer.writerow((home_status(test), test.path))
        temporary_path.replace(WPT_RESULTS_FILE)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def result_status(test: WptTest) -> str:
    return load_result_statuses().get(test.path, home_status(test))


def render_context(test: WptTest, render_name: str) -> dict[str, object]:
    try:
        render_label = RENDER_LABELS[render_name]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown render") from error
    directory = output_directory_for_wpt_path(test.path)
    asset = directory / "result.png"
    if render_name in {"reference", "diff"}:
        asset = directory / "reference.png"
    render_available = asset.is_file()
    if render_name == "approved-diff":
        render_available = render_available and approved_result_bytes(test) is not None
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
        raise HTTPException(status_code=404, detail="Test metadata not found")
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


def get_wpt_test(wpt_path: str) -> WptTest:
    test = next((test for test in load_wpt_tests() if test.path == wpt_path), None)
    if test is None:
        raise HTTPException(status_code=404, detail="WPT test not found")
    return test


app = FastAPI(
    title="Olive WPT Output Review",
    version="0.1.0",
    description="Review approved and current Olive WPT rendering output.",
)

app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    wpt_tests = load_wpt_tests()
    statuses = load_result_statuses()
    tests = [{"test": test, "status": statuses.get(test.path, "UNKN")} for test in wpt_tests]
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"tests": tests},
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


def approval_response(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    return templates.TemplateResponse(
        request=request,
        name="approval-controls.html",
        context={"test": test, "result_status": result_status(test), **report_context(test)},
    )


@app.post("/test-report/approve", response_class=HTMLResponse)
def approve_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    write_approval_status(test, "approved")
    write_result_statuses(load_wpt_tests())
    return approval_response(request, path)


@app.post("/test-report/unapprove", response_class=HTMLResponse)
def unapprove_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    write_approval_status(test, "pending")
    write_result_statuses(load_wpt_tests())
    return approval_response(request, path)


__all__ = ["app"]
