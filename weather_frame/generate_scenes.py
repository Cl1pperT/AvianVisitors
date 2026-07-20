"""Pre-generate location-specific watercolor weather scenes with Gemini.

This follows the bird-illustration pattern: a prompt plus positive references
goes to Gemini 3.1 Flash Lite Image, results are saved locally, and the Pi only
reads the completed PNG library. Existing files are skipped unless --force is
used.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from .scene_catalog import ENVIRONMENTS, SCENE_CONDITIONS
from .scene_catalog import choose_environment, condition_slug_for_forecast
from .weather import DailyForecast

GEMINI_MODEL = "gemini-3.1-flash-lite-image"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1/models/"
    f"{GEMINI_MODEL}:generateContent"
)
OUTPUT_SIZE = (1600, 1200)
DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def build_prompt(template: str, environment: str, condition: str) -> str:
    place = ENVIRONMENTS[environment]
    weather = SCENE_CONDITIONS[condition]
    return (
        template.replace("{environment_name}", place.name)
        .replace("{environment_description}", place.description)
        .replace("{weather_name}", weather.name)
        .replace("{weather_description}", weather.description)
        .replace(
            "{activity_guidance}",
            "Keep the landscape unoccupied; no specific activity is requested.",
        )
    )


def build_daily_prompt(
    template: str,
    environment: str,
    condition: str,
    forecast: DailyForecast,
    activities: tuple[str, ...],
) -> str:
    """Build a live-forecast prompt with five season-ranked activity choices."""
    candidates = ", ".join(activities)
    guidance = (
        f"Include one or two of these activities: {candidates}. Show them naturally "
        "with small figures or recognizable equipment while the landscape and "
        "weather remain dominant."
    )
    prompt = build_prompt(template, environment, condition)
    prompt = prompt.replace(
        "Keep the landscape unoccupied; no specific activity is requested.", guidance
    )
    exact_weather = (
        f"High {forecast.high_c:.1f}°C, low {forecast.low_c:.1f}°C; "
        f"precipitation {forecast.precipitation_probability}% / "
        f"{forecast.precipitation_mm:.1f} mm; snow {forecast.snowfall_cm:.1f} cm; "
        f"cloud cover {forecast.cloud_cover_mean:.0f}%; wind "
        f"{forecast.wind_speed_max_kmh:.0f} km/h, gusting "
        f"{forecast.wind_gust_max_kmh:.0f} km/h."
    )
    return f"{prompt.rstrip()}\n\nToday's forecast: {exact_weather}\n"


def discover_style_references(directory: Path) -> dict[str, Path]:
    files = sorted(
        path for path in directory.glob("*")
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    if not files:
        return {}
    # The current Goal Images were authored in this chronological order:
    # clear/summer, snow, storm. Descriptive filenames can override that.
    by_name = {}
    for path in files:
        lower = path.name.lower()
        if "snow" in lower:
            by_name["snow"] = path
        elif any(word in lower for word in ("storm", "rain", "thunder")):
            by_name["storm"] = path
        elif any(word in lower for word in ("sun", "clear", "summer")):
            by_name["sunny"] = path
    for mood, index in (("sunny", 0), ("snow", 1), ("storm", 2)):
        if mood not in by_name:
            by_name[mood] = files[min(index, len(files) - 1)]
    return by_name


def select_style_reference(condition: str, references: dict[str, Path]) -> Path | None:
    mood = SCENE_CONDITIONS[condition].reference_mood
    return references.get(mood) or references.get("sunny")


def _mime(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


def _reference_part(path: Path, max_side: int = 896) -> dict:
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
    return {
        "inline_data": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(buffer.getvalue()).decode(),
        }
    }


def build_gemini_payload(
    prompt: str,
    *,
    style_reference: Path | None,
    geography_reference: Path | None,
) -> dict:
    """Build the tested image-only request sent to Gemini."""
    parts: list[dict] = [{"text": prompt}]
    if geography_reference:
        parts.append({"text": "POSITIVE GEOGRAPHY REFERENCE (identity and viewpoint only):"})
        parts.append(_reference_part(geography_reference))
    if style_reference:
        parts.append({"text": "POSITIVE STYLE REFERENCE (watercolor technique and atmosphere only):"})
        parts.append(_reference_part(style_reference))
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            # GenerateContent currently accepts these human-readable values in
            # imageConfig. Its newer responseFormat enum rejects the documented
            # "4:3" and "1K" strings on the v1 REST endpoint.
            "imageConfig": {
                "aspectRatio": "4:3",
                "imageSize": "1K",
            },
        },
    }


def image_bytes_from_response(response: dict) -> bytes:
    """Return the final image, ignoring Gemini's optional thought images."""
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("thought"):
                continue
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    finish = (response.get("candidates") or [{}])[0].get("finishReason", "?")
    block = response.get("promptFeedback", {}).get("blockReason", "")
    raise RuntimeError(f"Gemini returned no image (finish={finish} block={block})")


def call_gemini(
    api_key: str,
    prompt: str,
    *,
    style_reference: Path | None,
    geography_reference: Path | None,
) -> bytes:
    payload = build_gemini_payload(
        prompt,
        style_reference=style_reference,
        geography_reference=geography_reference,
    )
    request = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    backoff = 4.0
    response = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as handle:
                response = json.loads(handle.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else backoff
                except (TypeError, ValueError):
                    delay = backoff
                time.sleep(delay)
                backoff *= 2
                continue
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if api_key:
                detail = detail.replace(api_key, "[redacted]")
            raise RuntimeError(
                f"Gemini API HTTP {exc.code}: {detail[:2000] or exc.reason}"
            ) from exc
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    return image_bytes_from_response(response or {})


def normalize_png(data: bytes, path: Path) -> None:
    with Image.open(BytesIO(data)) as source:
        image = ImageOps.fit(
            source.convert("RGB"),
            OUTPUT_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    image.save(temporary, format="PNG", optimize=True)
    os.replace(temporary, path)


def image_from_response(data: bytes) -> Image.Image:
    """Normalize model output to a full-size in-memory RGB scene."""
    with Image.open(BytesIO(data)) as source:
        return ImageOps.fit(
            source.convert("RGB"),
            OUTPUT_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )


def generate_daily_scene(
    forecast: DailyForecast,
    activities: tuple[str, ...],
    *,
    api_key: str,
    environment: str = "auto",
    template_path: Path | None = None,
    styles_path: Path | None = None,
    environment_refs_path: Path | None = None,
) -> Image.Image:
    """Generate one scene from today's forecast and five activity candidates."""
    if len(activities) != 5:
        raise ValueError("daily scene generation requires exactly five activities")
    environment_slug = choose_environment(forecast, environment)
    condition_slug = condition_slug_for_forecast(forecast)
    template_path = template_path or Path(__file__).parent / "scene_prompt.template.md"
    styles_path = styles_path or _default_styles()
    environment_refs_path = (
        environment_refs_path
        or Path(__file__).parent / "assets" / "references" / "environments"
    )
    references = discover_style_references(styles_path)
    style_reference = select_style_reference(condition_slug, references)
    geography_reference = next(
        (
            environment_refs_path / f"{environment_slug}{suffix}"
            for suffix in (".png", ".jpg", ".jpeg", ".webp")
            if (environment_refs_path / f"{environment_slug}{suffix}").is_file()
        ),
        None,
    )
    prompt = build_daily_prompt(
        template_path.read_text(),
        environment_slug,
        condition_slug,
        forecast,
        activities,
    )
    data = call_gemini(
        api_key,
        prompt,
        style_reference=style_reference,
        geography_reference=geography_reference,
    )
    return image_from_response(data)


def _default_styles() -> Path:
    sibling = Path(__file__).resolve().parents[2] / "goalimages"
    if sibling.is_dir():
        return sibling
    return Path(__file__).parent / "assets" / "references" / "styles"


def load_gemini_api_key(dotenv_path: Path = DOTENV_PATH) -> str:
    """Load the key from the environment, then the repo-local ignored .env."""
    environment_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if environment_key:
        return environment_key
    try:
        lines = dotenv_path.read_text().splitlines()
    except FileNotFoundError:
        return ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "GEMINI_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value.strip()
    return ""


def _selected(args) -> list[tuple[str, str]]:
    if args.all:
        environments = list(ENVIRONMENTS)
        conditions = list(SCENE_CONDITIONS)
    else:
        if not args.environment and not args.condition:
            raise ValueError("select --environment, --condition, or --all")
        environments = args.environment or list(ENVIRONMENTS)
        conditions = args.condition or list(SCENE_CONDITIONS)
    jobs = [(environment, condition) for environment in environments for condition in conditions]
    return jobs[: args.limit or None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", action="append", choices=ENVIRONMENTS)
    parser.add_argument("--condition", action="append", choices=SCENE_CONDITIONS)
    parser.add_argument("--all", action="store_true", help="generate the complete environment x condition matrix")
    parser.add_argument("--limit", type=int, default=0, help="cap jobs after selection")
    parser.add_argument("--force", action="store_true", help="replace existing scene files")
    parser.add_argument("--dry-run", action="store_true", help="print selected jobs and prompts without an API key")
    parser.add_argument("--sleep", type=float, default=6.0, help="seconds between API calls")
    parser.add_argument("--gemini-key", default=load_gemini_api_key())
    parser.add_argument("--styles", type=Path, default=_default_styles())
    parser.add_argument(
        "--environment-refs",
        type=Path,
        default=Path(__file__).parent / "assets" / "references" / "environments",
    )
    parser.add_argument("--prompt", type=Path, default=Path(__file__).parent / "scene_prompt.template.md")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "assets" / "scenes")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        jobs = _selected(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.dry_run and not args.gemini_key:
        print(
            f"error: GEMINI_API_KEY required (--gemini-key, environment, or {DOTENV_PATH})",
            file=sys.stderr,
        )
        return 2
    template = args.prompt.read_text()
    style_references = discover_style_references(args.styles)
    if not style_references:
        print(f"warning: no style references found in {args.styles}", file=sys.stderr)

    generated = skipped = failed = 0
    for index, (environment, condition) in enumerate(jobs):
        output = args.out / environment / f"{condition}.png"
        prompt = build_prompt(template, environment, condition)
        style_reference = select_style_reference(condition, style_references)
        geography_reference = next(
            (
                args.environment_refs / f"{environment}{suffix}"
                for suffix in (".png", ".jpg", ".jpeg", ".webp")
                if (args.environment_refs / f"{environment}{suffix}").is_file()
            ),
            None,
        )
        if output.exists() and not args.force:
            skipped += 1
            print(f"[skip] {environment}/{condition}")
            continue
        if args.dry_run:
            style_name = style_reference.name if style_reference else "none"
            geo_name = geography_reference.name if geography_reference else "none"
            print(f"[plan] {environment}/{condition} style={style_name} geography={geo_name}")
            print(prompt)
            continue
        try:
            data = call_gemini(
                args.gemini_key,
                prompt,
                style_reference=style_reference,
                geography_reference=geography_reference,
            )
            normalize_png(data, output)
            generated += 1
            print(f"[ok] {output} ({output.stat().st_size // 1024} KB)")
        except (OSError, RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            failed += 1
            print(f"[fail] {environment}/{condition}: {exc}", file=sys.stderr)
        if not args.dry_run and index < len(jobs) - 1:
            time.sleep(args.sleep)
    print(f"generated {generated} · skipped {skipped} · failed {failed} · selected {len(jobs)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
