#!/usr/bin/env python3

"""Create a labeled Olive/reference/diff review image for one WPT output."""

from __future__ import annotations

import argparse
from pathlib import Path
from pathlib import PurePosixPath

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageEnhance, ImageFont, ImageOps


BACKGROUND = ImageColor.getrgb("#dddddd")
IMAGE_BACKGROUND = ImageColor.getrgb("#ffffff")
TEXT_COLOR = ImageColor.getrgb("#222222")
PADDING = 24
LABEL_GAP = 8
SECTION_GAP = 28
LABEL_SIZE = 22
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a labeled Olive/reference/diff review image."
    )
    parser.add_argument(
        "path",
        help=(
            "WPT-relative source path or output directory containing "
            "reference.png and result.png"
        ),
    )
    return parser.parse_args()


def output_directory_for_wpt_path(wpt_path: str) -> Path:
    source = PurePosixPath(wpt_path)
    if source.is_absolute() or ".." in source.parts:
        raise SystemExit(f"WPT path must be relative and contain no '..': {wpt_path}")

    suffix = source.suffix.removeprefix(".")
    stem = source.name[: -(len(suffix) + 1)] if suffix else source.name
    output_name = f"{stem}-{suffix}-test" if suffix else f"{stem}-test"
    return PROJECT_ROOT.joinpath("outputs", *source.parts[:-1], output_name)


def resolve_output_directory(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate

    output_directory = output_directory_for_wpt_path(path)
    if output_directory.is_dir():
        return output_directory

    raise SystemExit(
        f"No WPT output directory found for {path}; tried {output_directory}"
    )


def load_rgb(path: Path) -> Image.Image:
    try:
        image = Image.open(path)
        image.load()
    except OSError as error:
        raise SystemExit(f"Unable to read {path}: {error}") from error

    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, IMAGE_BACKGROUND + (255,))
        return Image.alpha_composite(background, image).convert("RGB")
    return image.convert("RGB")


def fit_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, IMAGE_BACKGROUND)
    offset = ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


def diff_image(olive: Image.Image, reference: Image.Image) -> Image.Image:
    difference = ImageChops.difference(olive, reference).convert("L")
    difference = ImageEnhance.Contrast(difference).enhance(4.0)
    # Keep unchanged pixels light and map differing pixels to increasingly
    # saturated red, making subtle raster differences easy to review.
    return ImageOps.colorize(
        difference,
        black=ImageColor.getrgb("#f5f5f5"),
        white=ImageColor.getrgb("#d00000"),
    )


def load_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, LABEL_SIZE)
    return ImageFont.load_default()


def create_review_image(output_directory: Path) -> Path:
    if not output_directory.is_dir():
        raise SystemExit(f"Output directory does not exist: {output_directory}")

    olive_path = output_directory / "result.png"
    reference_path = output_directory / "reference.png"
    missing = [str(path) for path in (olive_path, reference_path) if not path.is_file()]
    if missing:
        raise SystemExit("Missing required image(s): " + ", ".join(missing))

    olive = load_rgb(olive_path)
    reference = load_rgb(reference_path)
    image_size = (max(olive.width, reference.width), max(olive.height, reference.height))
    olive_panel = fit_canvas(olive, image_size)
    reference_panel = fit_canvas(reference, image_size)
    difference_panel = diff_image(olive_panel, reference_panel)

    font = load_font()
    labels = ("1. Olive render", "2. Chromium render", "3. Image diff")
    label_height = max(font.getbbox(label)[3] for label in labels)
    section_height = label_height + LABEL_GAP + image_size[1]
    composite = Image.new(
        "RGB",
        (image_size[0] + (PADDING * 2), (section_height * 3) + (SECTION_GAP * 2) + (PADDING * 2)),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(composite)

    for index, (label, panel) in enumerate(
        zip(labels, (olive_panel, reference_panel, difference_panel), strict=True)
    ):
        section_top = PADDING + (index * (section_height + SECTION_GAP))
        draw.text((PADDING, section_top), label, fill=TEXT_COLOR, font=font)
        image_top = section_top + label_height + LABEL_GAP
        composite.paste(panel, (PADDING, image_top))

    review_path = output_directory / "review.png"
    composite.save(review_path, format="PNG")
    return review_path


if __name__ == "__main__":
    arguments = parse_args()
    created = create_review_image(resolve_output_directory(arguments.path))
    print(f"WPT_REVIEW_IMAGE_CREATED path={created}")
