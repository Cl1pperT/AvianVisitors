"""Pre-generate location-specific watercolor weather scenes with Gemini.

This follows the bird-illustration pattern: a prompt plus positive references
goes to Gemini 2.5 Flash Image, results are saved locally, and the Pi only reads
the completed PNG library. Existing files are skipped unless --force is used.
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

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-image:generateContent"
)
OUTPUT_SIZE = (1600, 1200)


def build_prompt(template: str, environment: str, condition: str) -> str:
    place = ENVIRONMENTS[environment]
    weather = SCENE_CONDITIONS[condition]
    return (
        template.replace("{environment_name}", place.name)
        .replace("{environment_description}", place.description)
        .replace("{weather_name}", weather.name)
        .replace("{weather_description}", weather.description)
    )


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


def call_gemini(
    api_key: str,
    prompt: str,
    *,
    style_reference: Path | None,
    geography_reference: Path | None,
) -> bytes:
    parts: list[dict] = [{"text": prompt}]
    if geography_reference:
        parts.append({"text": "POSITIVE GEOGRAPHY REFERENCE (identity and viewpoint only):"})
        parts.append(_reference_part(geography_reference))
    if style_reference:
        parts.append({"text": "POSITIVE STYLE REFERENCE (watercolor technique and atmosphere only):"})
        parts.append(_reference_part(style_reference))
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
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
            raise
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    for candidate in (response or {}).get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    finish = ((response or {}).get("candidates") or [{}])[0].get("finishReason", "?")
    block = (response or {}).get("promptFeedback", {}).get("blockReason", "")
    raise RuntimeError(f"Gemini returned no image (finish={finish} block={block})")


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


def _default_styles() -> Path:
    sibling = Path(__file__).resolve().parents[2] / "goalimages"
    if sibling.is_dir():
        return sibling
    return Path(__file__).parent / "assets" / "references" / "styles"


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
    parser.add_argument("--gemini-key", default=os.environ.get("GEMINI_API_KEY", ""))
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
        print("error: GEMINI_API_KEY required (--gemini-key or env)", file=sys.stderr)
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
