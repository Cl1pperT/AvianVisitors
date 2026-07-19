"""Deterministic, limited-palette scenic weather artwork."""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from frame import display as panel

from .scene_catalog import generated_scene_path
from .weather import Condition, DailyForecast, PrecipitationPeriod


@dataclass(frozen=True)
class Style:
    paper: tuple[int, int, int]
    ink: tuple[int, int, int]
    blue: tuple[int, int, int]
    red: tuple[int, int, int]
    yellow: tuple[int, int, int]
    green: tuple[int, int, int]
    outline_width: int
    texture: float


STYLES = {
    "woodblock": Style(
        paper=(236, 234, 223),
        ink=(26, 26, 28),
        blue=(49, 71, 130),
        red=(165, 60, 56),
        yellow=(198, 176, 74),
        green=(58, 110, 72),
        outline_width=3,
        texture=1.0,
    ),
    "ink_wash": Style(
        paper=(236, 234, 223),
        ink=(73, 74, 75),
        blue=(86, 105, 139),
        red=(164, 92, 83),
        yellow=(190, 175, 112),
        green=(91, 119, 92),
        outline_width=1,
        texture=0.55,
    ),
}

CONDITION_LABELS = {
    Condition.CLEAR: "Clear",
    Condition.CLOUDY: "Cloudy",
    Condition.FOG: "Fog",
    Condition.RAIN: "Rain",
    Condition.SNOW: "Snow",
    Condition.THUNDER: "Thunderstorms",
}

CAPTION_HEIGHT = 73
CAPTION_FONT_SIZE = 28
CAPTION_MIN_FONT_SIZE = 22
CAPTION_MARGIN = 28
CAPTION_GAP = 36

ASSET_ROOT = Path(__file__).parent / "assets" / "mountains"
MOUNTAIN_CONDITIONS = ("sun", "snow", "clouds", "melting_snow")
CANONICAL_COLORS = {
    (236, 234, 223): "paper",
    (26, 26, 28): "ink",
    (49, 71, 130): "blue",
    (165, 60, 56): "red",
    (198, 176, 74): "yellow",
    (58, 110, 72): "green",
}


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def _seed(forecast: DailyForecast, style: str) -> int:
    fields = (
        forecast.date.isoformat(),
        round(forecast.latitude, 3),
        round(forecast.longitude, 3),
        forecast.weather_code,
        round(forecast.high_c, 1),
        round(forecast.low_c, 1),
        forecast.precipitation_probability,
        round(forecast.precipitation_mm, 1),
        round(forecast.cloud_cover_mean),
        round(forecast.wind_speed_max_kmh),
        forecast.precipitation_period.value,
        style,
    )
    return int.from_bytes(hashlib.sha256(repr(fields).encode()).digest()[:8], "big")


def mountain_condition_for_forecast(forecast: DailyForecast) -> str:
    if forecast.condition == Condition.SNOW or forecast.snowfall_cm > 0:
        return "melting_snow" if forecast.high_c > 2 else "snow"
    if forecast.condition == Condition.CLEAR:
        return "sun"
    return "clouds"


@lru_cache(maxsize=1)
def available_mountains() -> tuple[str, ...]:
    """Names that have an aligned PNG in every weather-condition folder."""
    sets = []
    for condition in MOUNTAIN_CONDITIONS:
        directory = ASSET_ROOT / condition
        sets.append({path.stem for path in directory.glob("*.png")} if directory.is_dir() else set())
    if not sets:
        return ()
    return tuple(sorted(set.intersection(*sets)))


def mountain_component_for_forecast(forecast: DailyForecast) -> tuple[str, str, Path] | None:
    names = available_mountains()
    if not names:
        return None
    identity = (
        forecast.date.isoformat(),
        round(forecast.latitude, 3),
        round(forecast.longitude, 3),
    )
    index = int.from_bytes(hashlib.sha256(repr(identity).encode()).digest()[:8], "big") % len(names)
    condition = mountain_condition_for_forecast(forecast)
    name = names[index]
    return name, condition, ASSET_ROOT / condition / f"{name}.png"


def _recolor_component(image: Image.Image, style: Style) -> Image.Image:
    targets = {
        key: getattr(style, semantic)
        for key, semantic in CANONICAL_COLORS.items()
    }
    pixels = []
    rgba = image.convert("RGBA")
    source_pixels = (
        rgba.get_flattened_data()
        if hasattr(rgba, "get_flattened_data")
        else rgba.getdata()
    )
    for red, green, blue, alpha in source_pixels:
        replacement = targets.get((red, green, blue), (red, green, blue))
        pixels.append((*replacement, alpha))
    recolored = Image.new("RGBA", image.size)
    recolored.putdata(pixels)
    return recolored


def _load_mountain_component(forecast: DailyForecast, style: Style, width: int) -> Image.Image | None:
    selection = mountain_component_for_forecast(forecast)
    if selection is None:
        return None
    _name, _condition, path = selection
    try:
        with Image.open(path) as source:
            component = _recolor_component(source, style)
    except (OSError, ValueError):
        return None
    if component.width != width:
        scale = width / component.width
        component = component.resize((width, max(1, round(component.height * scale))), Image.Resampling.LANCZOS)
    return component


def _load_generated_scene(
    forecast: DailyForecast,
    environment: str,
) -> tuple[Image.Image | None, str, str, Path]:
    environment_slug, condition_slug, path = generated_scene_path(forecast, environment)
    if not path.is_file():
        return None, environment_slug, condition_slug, path
    with Image.open(path) as source:
        image = ImageOps.fit(
            source.convert("RGB"),
            (panel.PANEL_H, panel.PANEL_W),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    return image, environment_slug, condition_slug, path


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10 compatibility
        return ImageFont.load_default()


def _sky_colors(forecast: DailyForecast, style: Style, hot_dry: bool):
    if forecast.condition == Condition.THUNDER:
        return _blend(style.ink, style.blue, 0.45), _blend(style.paper, style.blue, 0.42)
    if forecast.condition == Condition.RAIN:
        return _blend(style.ink, style.blue, 0.68), _blend(style.paper, style.blue, 0.32)
    if forecast.condition == Condition.SNOW:
        return _blend(style.paper, style.blue, 0.46), _blend(style.paper, style.blue, 0.17)
    if forecast.condition in (Condition.FOG, Condition.CLOUDY):
        return _blend(style.paper, style.blue, 0.34), _blend(style.paper, style.yellow, 0.16)
    if hot_dry:
        return _blend(style.paper, style.blue, 0.42), _blend(style.paper, style.yellow, 0.7)
    return _blend(style.paper, style.blue, 0.62), _blend(style.paper, style.yellow, 0.38)


def _gradient(draw: ImageDraw.ImageDraw, width: int, y1: int, top, bottom):
    for y in range(y1):
        draw.line((0, y, width, y), fill=_blend(top, bottom, y / max(1, y1 - 1)))


def _mountain_points(rng: random.Random, width: int, base: int, amplitude: int, step: int):
    points = [(0, base)]
    x = -step
    while x < width + step:
        peak_x = x + round(step * rng.uniform(0.38, 0.62))
        peak_y = base - rng.randint(max(8, amplitude // 3), amplitude)
        points.extend(
            (
                (x, base - rng.randint(0, max(2, amplitude // 12))),
                (x + step // 4, base - rng.randint(amplitude // 8, max(amplitude // 7, amplitude // 3))),
                (peak_x, peak_y),
                (x + round(step * 0.78), base - rng.randint(amplitude // 10, max(amplitude // 9, amplitude // 4))),
                (x + step, base - rng.randint(0, max(2, amplitude // 12))),
            )
        )
        x += step
    points.extend(((width, base + amplitude), (0, base + amplitude)))
    return points


def _draw_cloud(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    center: tuple[int, int],
    width: int,
    height: int,
    fill,
):
    cx, cy = center
    lobes = max(4, width // 75)
    boxes = []
    for i in range(lobes):
        lw = rng.randint(max(35, width // 5), max(50, width // 3))
        lh = rng.randint(max(22, height // 2), max(30, height))
        lx = round(cx - width / 2 + i * width / max(1, lobes - 1) - lw / 2)
        ly = cy - rng.randint(0, max(1, height // 3))
        boxes.append((lx, ly, lx + lw, ly + lh))
    base = (cx - width // 2, cy, cx + width // 2, cy + height // 2)
    for box in boxes:
        draw.ellipse(box, fill=fill)
    # A filled base unifies the overlapping lobes. Outlining every ellipse or
    # the rounded base reads as bubbles after e-ink quantization, so clouds use
    # their limited-palette edge as the silhouette.
    draw.rounded_rectangle(base, radius=max(8, height // 4), fill=fill)


def _cloud_center_x(period: PrecipitationPeriod, width: int) -> int:
    return {
        PrecipitationPeriod.MORNING: round(width * 0.31),
        PrecipitationPeriod.AFTERNOON: round(width * 0.68),
        PrecipitationPeriod.EVENING: round(width * 0.79),
        PrecipitationPeriod.NONE: round(width * 0.58),
    }[period]


def _draw_precipitation(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    forecast: DailyForecast,
    style: Style,
    cloud_x: int,
    cloud_y: int,
    width: int,
    horizon: int,
):
    if forecast.condition == Condition.SNOW or forecast.snowfall_cm > 0:
        count = round(85 + min(180, forecast.snowfall_cm * 30))
        for _ in range(count):
            x = rng.randrange(20, width - 20)
            y = rng.randrange(cloud_y + 45, horizon + 180)
            radius = rng.choice((2, 2, 3, 4))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=style.paper)
        return
    if forecast.condition not in (Condition.RAIN, Condition.THUNDER):
        return

    left, right = cloud_x - width // 4, cloud_x + width // 4
    virga = forecast.precipitation_mm < 0.5
    count = 22 if virga else 48 + min(45, round(forecast.precipitation_mm * 5))
    color = _blend(style.blue, style.ink, 0.35)
    for _ in range(count):
        x = rng.randint(max(8, left), min(width - 8, right))
        y = rng.randint(cloud_y + 55, cloud_y + 115)
        length = rng.randint(45, 130 if virga else 210)
        if virga:
            length = min(length, max(30, horizon - y - rng.randint(35, 100)))
        draw.line((x, y, x - 12, y + length), fill=color, width=rng.choice((1, 2, 3)))
    if forecast.condition == Condition.THUNDER:
        bolt_x = cloud_x + rng.randint(-55, 55)
        draw.line(
            (
                bolt_x,
                cloud_y + 55,
                bolt_x - 24,
                cloud_y + 115,
                bolt_x + 4,
                cloud_y + 108,
                bolt_x - 30,
                cloud_y + 185,
            ),
            fill=style.yellow,
            width=7,
        )


def _draw_wind(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    forecast: DailyForecast,
    style: Style,
    width: int,
    horizon: int,
    height: int,
):
    if forecast.wind_speed_max_kmh < 30 and forecast.wind_gust_max_kmh < 45:
        return
    radians = math.radians((forecast.wind_direction_deg + 180) % 360)
    direction = 1 if math.cos(radians) >= 0 else -1
    color = _blend(style.blue, style.paper, 0.28)
    for i in range(12):
        y = round(height * 0.16) + i * 31 + rng.randint(-9, 9)
        x0 = rng.randint(10, width // 3)
        length = rng.randint(width // 4, width // 2)
        points = []
        for p in range(7):
            x = x0 + direction * round(length * p / 6)
            yy = y + round(math.sin(p * 1.25 + i) * 8)
            points.append((x, yy))
        draw.line(points, fill=color, width=2)
    grass_color = _blend(style.green, style.ink, 0.25)
    lean = direction * min(32, round(forecast.wind_speed_max_kmh / 2))
    for x in range(25, width, 27):
        base_y = rng.randint(horizon + 150, height - 15)
        stalk = rng.randint(25, 65)
        draw.line((x, base_y, x + lean, base_y - stalk), fill=grass_color, width=2)


def _draw_texture(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    style: Style,
    width: int,
    height: int,
    horizon: int,
):
    dot_count = round(width * height / 2100 * style.texture)
    faint = _blend(style.paper, style.ink, 0.16)
    for _ in range(dot_count):
        x, y = rng.randrange(width), rng.randrange(height)
        draw.point((x, y), fill=faint)
    hatch_count = round(75 * style.texture)
    hatch = _blend(style.green, style.ink, 0.34)
    for _ in range(hatch_count):
        x = rng.randrange(5, width - 20)
        y = rng.randrange(horizon + 90, height - 10)
        length = rng.randint(10, 38)
        draw.line((x, y, x + length, y - rng.randint(2, 12)), fill=hatch, width=1)


def _caption(draw: ImageDraw.ImageDraw, forecast: DailyForecast, style: Style, width: int, height: int, units: str):
    if units == "imperial":
        high = round(forecast.high_c * 9 / 5 + 32)
        low = round(forecast.low_c * 9 / 5 + 32)
        temperatures = f"{high}° / {low}°F"
    else:
        high, low = round(forecast.high_c), round(forecast.low_c)
        temperatures = f"{high}° / {low}°C"
    label = CONDITION_LABELS[forecast.condition]
    left = f"{forecast.location_name}  ·  {forecast.date:%a %b %-d}"
    right = f"{label}  ·  {temperatures}"

    font = _font(CAPTION_FONT_SIZE)
    for size in range(CAPTION_FONT_SIZE, CAPTION_MIN_FONT_SIZE - 1, -1):
        candidate = _font(size)
        left_box = draw.textbbox((0, 0), left, font=candidate)
        right_box = draw.textbbox((0, 0), right, font=candidate)
        total_width = (
            left_box[2] - left_box[0]
            + right_box[2] - right_box[0]
            + CAPTION_GAP
            + 2 * CAPTION_MARGIN
        )
        font = candidate
        if total_width <= width:
            break

    left_box = draw.textbbox((0, 0), left, font=font)
    right_box = draw.textbbox((0, 0), right, font=font)
    top = height - CAPTION_HEIGHT
    draw.rectangle((0, top, width, height), fill=_blend(style.paper, style.yellow, 0.08))
    draw.line((24, top, width - 24, top), fill=_blend(style.ink, style.paper, 0.45), width=1)

    left_height = left_box[3] - left_box[1]
    right_height = right_box[3] - right_box[1]
    left_y = top + (CAPTION_HEIGHT - left_height) // 2 - left_box[1]
    right_y = top + (CAPTION_HEIGHT - right_height) // 2 - right_box[1]
    draw.text(
        (CAPTION_MARGIN, left_y),
        left,
        fill=style.ink,
        font=font,
    )
    draw.text(
        (width - CAPTION_MARGIN - (right_box[2] - right_box[0]), right_y),
        right,
        fill=style.ink,
        font=font,
    )


def render_forecast(
    forecast: DailyForecast,
    *,
    style: str = "woodblock",
    caption: bool = False,
    units: str = "imperial",
    scene_source: str = "auto",
    environment: str = "auto",
    scene_image: Image.Image | None = None,
) -> Image.Image:
    """Render a full-bleed image in the panel's native 1600x1200 orientation."""
    if style not in STYLES:
        raise ValueError(f"unknown render style {style!r}")
    if units not in ("imperial", "metric"):
        raise ValueError(f"units must be 'imperial' or 'metric', not {units!r}")
    if scene_source not in ("auto", "generated", "procedural", "ai"):
        raise ValueError("scene_source must be 'auto', 'generated', 'procedural', or 'ai'")
    palette = STYLES[style]

    if scene_image is not None:
        generated = ImageOps.fit(
            scene_image.convert("RGB"),
            (panel.PANEL_H, panel.PANEL_W),
            method=Image.Resampling.LANCZOS,
        )
        if caption:
            _caption(ImageDraw.Draw(generated), forecast, palette, generated.width, generated.height, units)
        return generated
    if scene_source == "ai":
        raise ValueError("scene_source 'ai' requires a generated scene image")

    if scene_source != "procedural":
        generated, environment_slug, condition_slug, path = _load_generated_scene(
            forecast, environment
        )
        if generated is not None:
            if caption:
                _caption(
                    ImageDraw.Draw(generated),
                    forecast,
                    palette,
                    generated.width,
                    generated.height,
                    units,
                )
            return generated
        if scene_source == "generated":
            raise FileNotFoundError(
                f"generated scene is missing for {environment_slug}/{condition_slug}: {path}"
            )

    rng = random.Random(_seed(forecast, style))

    width, height = panel.PANEL_H, panel.PANEL_W
    scene = Image.new("RGB", (width, height), palette.paper)
    draw = ImageDraw.Draw(scene)
    horizon = round(height * 0.61)
    hot_dry = forecast.high_c >= 30 and forecast.precipitation_mm < 1

    sky_top, sky_bottom = _sky_colors(forecast, palette, hot_dry)
    _gradient(draw, width, height, sky_top, sky_bottom)

    # The sun remains visible on unsettled days when precipitation arrives later,
    # making the daily sequence readable from left to right.
    if forecast.condition == Condition.CLEAR or (
        forecast.precipitation_period in (PrecipitationPeriod.AFTERNOON, PrecipitationPeriod.EVENING)
        and forecast.condition in (Condition.RAIN, Condition.THUNDER)
    ):
        sun_x = round(width * (0.27 if forecast.precipitation_period != PrecipitationPeriod.NONE else 0.68))
        sun_y = round(height * 0.25)
        radius = 55 if hot_dry else 45
        draw.ellipse((sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius),
                     fill=palette.yellow, outline=palette.red if hot_dry else palette.ink,
                     width=palette.outline_width)

    # A distant procedural ridge supplies depth. The hero range is selected from
    # aligned transparent components, using a stable identity and an independent
    # weather variant like the bird display's cutout assets.
    far = _mountain_points(rng, width, horizon + 45, 170, 170)
    draw.polygon(far, fill=_blend(palette.paper, palette.blue, 0.43))
    mountain = _load_mountain_component(forecast, palette, width)
    if mountain is not None:
        mountain_y = horizon - round(mountain.height * 0.38)
        scene.paste(mountain, (0, mountain_y), mountain)
    else:
        near = _mountain_points(rng, width, horizon + 145, 220, 220)
        land_color = _blend(palette.green, palette.ink, 0.23)
        if forecast.condition == Condition.SNOW:
            land_color = _blend(palette.blue, palette.paper, 0.22)
        draw.polygon(near, fill=land_color, outline=palette.ink, width=palette.outline_width)

    foreground = [
        (0, horizon + 210),
        (round(width * 0.18), horizon + 165),
        (round(width * 0.42), horizon + 235),
        (round(width * 0.66), horizon + 180),
        (width, horizon + 245),
        (width, height),
        (0, height),
    ]
    ground = _blend(palette.green, palette.ink, 0.43)
    if hot_dry:
        ground = _blend(palette.yellow, palette.red, 0.2)
    if forecast.condition == Condition.SNOW:
        ground = _blend(palette.paper, palette.blue, 0.14)
    draw.polygon(foreground, fill=ground, outline=palette.ink, width=palette.outline_width)

    cloud_cover = max(0, min(100, forecast.cloud_cover_mean))
    cloud_count = round(cloud_cover / 24)
    if forecast.condition in (Condition.RAIN, Condition.SNOW, Condition.THUNDER):
        cloud_count = max(3, cloud_count)
    cloud_x = _cloud_center_x(forecast.precipitation_period, width)
    cloud_y = round(height * 0.27)
    for index in range(cloud_count):
        spread = index - (cloud_count - 1) / 2
        cx = round(cloud_x + spread * 125 + rng.randint(-35, 35))
        cy = cloud_y + rng.randint(-45, 55)
        cw = rng.randint(190, 310)
        ch = rng.randint(65, 105)
        heavy = forecast.condition in (Condition.RAIN, Condition.THUNDER) and index >= cloud_count // 2
        fill = _blend(palette.paper, palette.blue, 0.38 if not heavy else 0.67)
        if forecast.condition == Condition.FOG:
            fill = _blend(palette.paper, palette.blue, 0.2)
        _draw_cloud(draw, rng, (cx, cy), cw, ch, fill)

    if forecast.condition == Condition.FOG:
        fog = _blend(palette.paper, palette.blue, 0.18)
        for index in range(7):
            y = horizon - 85 + index * 28
            inset = rng.randint(5, 70)
            draw.line((inset, y, width - inset, y + rng.randint(-4, 4)), fill=fog, width=11)

    _draw_precipitation(draw, rng, forecast, palette, cloud_x, cloud_y, width, horizon)
    _draw_wind(draw, rng, forecast, palette, width, horizon, height)
    _draw_texture(draw, rng, palette, width, height, horizon)

    if caption:
        _caption(draw, forecast, palette, width, height, units)

    return scene
