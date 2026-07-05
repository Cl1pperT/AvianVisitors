"""Generate aligned transparent mountain component variants.

The generated PNGs are intentionally ordinary assets, not a runtime cache.
They can be replaced one at a time with hand-drawn artwork as long as the
1600x420 transparent canvas and bottom baseline are preserved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 1600, 420
CONDITIONS = ("sun", "snow", "clouds", "melting_snow")

PAPER = (236, 234, 223, 255)
INK = (26, 26, 28, 255)
BLUE = (49, 71, 130, 255)
YELLOW = (198, 176, 74, 255)
GREEN = (58, 110, 72, 255)
RED = (165, 60, 56, 255)

# Each ridge is a reusable mountain identity. Peaks list (x, y, half-width,
# snow-depth) drives aligned snow and melt details on the same silhouette.
RANGES = {
    "alpine": {
        "ridge": [
            (0, 350), (120, 260), (225, 320), (390, 105), (515, 292),
            (675, 55), (815, 310), (1010, 135), (1145, 300),
            (1320, 90), (1480, 285), (1600, 220),
        ],
        "peaks": [(390, 105, 100, 85), (675, 55, 125, 110), (1010, 135, 95, 75), (1320, 90, 105, 90)],
    },
    "massif": {
        "ridge": [
            (0, 330), (145, 285), (310, 230), (470, 130), (575, 155),
            (700, 48), (835, 72), (970, 175), (1110, 145),
            (1265, 245), (1435, 205), (1600, 285),
        ],
        "peaks": [(470, 130, 95, 70), (700, 48, 145, 115), (835, 72, 105, 90), (1110, 145, 85, 65)],
    },
    "sawtooth": {
        "ridge": [
            (0, 315), (135, 170), (260, 300), (405, 125), (540, 305),
            (690, 155), (830, 320), (970, 105), (1115, 295),
            (1260, 145), (1390, 305), (1510, 185), (1600, 260),
        ],
        "peaks": [(135, 170, 80, 65), (405, 125, 95, 75), (690, 155, 85, 65),
                  (970, 105, 100, 85), (1260, 145, 90, 70), (1510, 185, 65, 50)],
    },
}


def _snow_cap(draw: ImageDraw.ImageDraw, peak, *, melting: bool = False):
    x, y, half_width, depth = peak
    if melting:
        half_width = round(half_width * 0.62)
        depth = round(depth * 0.52)
    points = [
        (x, y),
        (x - half_width, y + depth),
        (x - round(half_width * 0.42), y + round(depth * 0.72)),
        (x - round(half_width * 0.12), y + depth),
        (x + round(half_width * 0.18), y + round(depth * 0.62)),
        (x + round(half_width * 0.48), y + round(depth * 0.84)),
        (x + half_width, y + depth),
    ]
    draw.polygon(points, fill=PAPER)
    if melting:
        for offset in (-round(half_width * 0.35), round(half_width * 0.28)):
            start_y = y + round(depth * 0.68)
            draw.line((x + offset, start_y, x + offset - 8, start_y + 55), fill=BLUE, width=4)


def _cloud_band(draw: ImageDraw.ImageDraw, y: int, offset: int):
    fill = (236, 234, 223, 215)
    shadow = (49, 71, 130, 150)
    for x in range(-120 + offset, WIDTH + 160, 190):
        draw.ellipse((x, y, x + 260, y + 72), fill=shadow)
        draw.ellipse((x - 25, y - 18, x + 155, y + 58), fill=fill)
        draw.ellipse((x + 75, y - 32, x + 275, y + 60), fill=fill)


def render_range(name: str, condition: str) -> Image.Image:
    spec = RANGES[name]
    ridge = spec["ridge"]
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    mountain_fill = BLUE
    if condition == "clouds":
        mountain_fill = (49, 71, 130, 235)
    draw.polygon([*ridge, (WIDTH, HEIGHT), (0, HEIGHT)], fill=mountain_fill)

    # Faceted faces make the cutout hold together after six-color dithering.
    for index, peak in enumerate(spec["peaks"]):
        x, y, half_width, depth = peak
        left_color = YELLOW if condition == "sun" else (236, 234, 223, 120)
        if condition == "clouds":
            left_color = (26, 26, 28, 90)
        draw.polygon(
            [(x, y), (x - half_width, min(HEIGHT, y + depth * 2)),
             (x + round(half_width * 0.12), min(HEIGHT, y + depth * 2.4))],
            fill=left_color,
        )
        if condition == "sun" and index % 2:
            draw.line((x, y, x + half_width, y + depth * 2), fill=RED, width=3)

    if condition == "snow":
        for peak in spec["peaks"]:
            _snow_cap(draw, peak)
    elif condition == "melting_snow":
        for peak in spec["peaks"]:
            _snow_cap(draw, peak, melting=True)
        draw.line((0, 372, 300, 360, 620, 378, 910, 354, 1250, 375, 1600, 350),
                  fill=BLUE, width=5)
    elif condition == "sun":
        draw.polygon(
            [(0, 350), (260, 325), (520, 350), (815, 318), (1090, 352),
             (1370, 320), (WIDTH, 345), (WIDTH, HEIGHT), (0, HEIGHT)],
            fill=GREEN,
        )
    elif condition == "clouds":
        _cloud_band(draw, 205, 0)
        _cloud_band(draw, 290, 85)

    draw.line(ridge, fill=INK, width=4, joint="curve")
    return image


def generate(output: Path) -> list[str]:
    written = []
    for condition in CONDITIONS:
        directory = output / condition
        directory.mkdir(parents=True, exist_ok=True)
        for name in RANGES:
            path = directory / f"{name}.png"
            render_range(name, condition).save(path, format="PNG", optimize=True)
            written.append(str(path.relative_to(output.parent)))
    manifest = {
        "schema": 1,
        "size": [WIDTH, HEIGHT],
        "conditions": list(CONDITIONS),
        "mountains": list(RANGES),
        "files": written,
    }
    with (output / "manifest.json").open("w") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "assets" / "mountains",
    )
    args = parser.parse_args(argv)
    written = generate(args.output)
    print(f"generated {len(written)} mountain components in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
