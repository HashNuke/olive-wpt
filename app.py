"""FastAPI application for Olive WPT output review."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

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

templates = Jinja2Templates(directory=str(TEMPLATES_ROOT))


@dataclass(frozen=True, slots=True)
class WptTest:
    path: str
    url: str
    review_url: str


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
            review_url=f"/tests/{quote(path, safe='/')}",
        )
        for path in load_wpt_paths()
    )


def output_directory_for_wpt_path(wpt_path: str) -> Path:
    source_path = PurePosixPath(wpt_path)
    suffix = source_path.suffix.removeprefix(".")
    stem = source_path.name[: -(len(suffix) + 1)] if suffix else source_path.name
    output_name = f"{stem}-{suffix}-test" if suffix else f"{stem}-test"
    return OUTPUTS_ROOT.joinpath(*source_path.parts[:-1], output_name)


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


@app.get("/tests/{wpt_path:path}", response_class=HTMLResponse)
def test_review(request: Request, wpt_path: str) -> HTMLResponse:
    test = get_wpt_test(wpt_path)
    output_directory = output_directory_for_wpt_path(test.path)
    return templates.TemplateResponse(
        request=request,
        name="test-review.html",
        context={
            "test": test,
            "olive_available": (output_directory / "result.png").is_file(),
            "chrome_available": (output_directory / "reference.png").is_file(),
        },
    )


@app.get("/test-assets/{wpt_path:path}/{asset_name}")
def test_asset(wpt_path: str, asset_name: str) -> FileResponse:
    if asset_name not in {"result.png", "reference.png"}:
        raise HTTPException(status_code=404, detail="Test asset not found")

    test = get_wpt_test(wpt_path)
    asset = output_directory_for_wpt_path(test.path) / asset_name
    if not asset.is_file():
        raise HTTPException(status_code=404, detail="Test asset not found")
    return FileResponse(asset, media_type="image/png")


__all__ = ["app"]
