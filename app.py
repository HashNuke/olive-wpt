"""FastAPI application scaffold for Olive WPT output review."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PROJECT_ROOT / "static"
TEMPLATES_ROOT = PROJECT_ROOT / "templates"

app = FastAPI(
    title="Olive WPT Output Review",
    version="0.1.0",
    description="Review approved and current Olive WPT rendering output.",
)

# Static assets are mounted now; application page routes are intentionally
# deferred to the next checkpoint.
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


__all__ = ["app"]
