"""FastAPI application for Olive WPT output review."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PROJECT_ROOT / "static"
TEMPLATES_ROOT = PROJECT_ROOT / "templates"
WPT_PATHS_FILE = PROJECT_ROOT / "wpt_paths.txt"
WPT_LIVE_ROOT = "https://wpt.live"

templates = Jinja2Templates(directory=str(TEMPLATES_ROOT))


@dataclass(frozen=True, slots=True)
class WptTest:
    path: str
    url: str


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
        WptTest(path=path, url=f"{WPT_LIVE_ROOT}/{quote(path, safe='/')}")
        for path in load_wpt_paths()
    )


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


__all__ = ["app"]
