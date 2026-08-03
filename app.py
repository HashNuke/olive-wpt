"""FastAPI application for Olive WPT output review."""

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PROJECT_ROOT / "static"
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
OUTPUTS_ROOT = PROJECT_ROOT / "outputs"
WPT_PATHS_FILE = PROJECT_ROOT / "wpt_paths.txt"
WPT_LIVE_ROOT = "https://wpt.live"
RENDER_ASSETS = {
    "olive": ("result.png", "Olive render"),
    "reference": ("reference.png", "Chrome render"),
    "diff": ("result-vs-reference.png", "Olive vs Chrome diff"),
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


def approval_context(test: WptTest) -> dict[str, object]:
    metadata = load_metadata(test)
    output_directory = output_directory_for_wpt_path(test.path)
    return {
        "approval_status": "approved" if metadata and metadata.get("status") == "approved" else "pending",
        "metadata_available": metadata is not None,
        "olive_available": (output_directory / "result.png").is_file(),
    }


def render_context(test: WptTest, render_name: str) -> dict[str, object]:
    try:
        asset_name, render_label = RENDER_ASSETS[render_name]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Unknown render") from error
    asset = output_directory_for_wpt_path(test.path) / asset_name
    return {
        "test": test,
        "render_label": render_label,
        "render_name": render_name,
        "render_available": asset.is_file(),
        "image_url": test.asset_url(render_name),
    }


def write_approval_status(test: WptTest, status: str) -> None:
    metadata_path = metadata_path_for_wpt_path(test.path)
    metadata = load_metadata(test)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Test metadata not found")
    if not (output_directory_for_wpt_path(test.path) / "result.png").is_file():
        raise HTTPException(status_code=409, detail="Olive render is not available")

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
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"tests": load_wpt_tests()},
    )


@app.get("/test-report/view", response_class=HTMLResponse)
def test_review(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    return templates.TemplateResponse(
        request=request,
        name="test-review.html",
        context={
            "test": test,
            **approval_context(test),
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
def test_image(path: str, render: str = "olive") -> FileResponse:
    test = get_wpt_test(path)
    render_context(test, render)
    asset_name, _ = RENDER_ASSETS[render]
    asset = output_directory_for_wpt_path(test.path) / asset_name
    if not asset.is_file():
        raise HTTPException(status_code=404, detail="Test asset not found")
    return FileResponse(asset, media_type="image/png")


def approval_response(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    return templates.TemplateResponse(
        request=request,
        name="approval-controls.html",
        context={"test": test, **approval_context(test)},
    )


@app.post("/test-report/approve", response_class=HTMLResponse)
def approve_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    write_approval_status(test, "approved")
    return approval_response(request, path)


@app.post("/test-report/unapprove", response_class=HTMLResponse)
def unapprove_test(request: Request, path: str) -> HTMLResponse:
    test = get_wpt_test(path)
    write_approval_status(test, "pending")
    return approval_response(request, path)


__all__ = ["app"]
