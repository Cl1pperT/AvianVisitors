"""Generate curated, weather-appropriate activity variants with Gemini.

Each job starts from an existing weather-only scene and writes to a separate
activity-scene library. The completed base scene is never modified.
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from .generate_scenes import call_gemini, load_gemini_api_key, normalize_png
from .scene_catalog import ENVIRONMENTS, SCENE_CONDITIONS


@dataclass(frozen=True)
class ActivitySceneJob:
    slug: str
    name: str
    environment: str
    condition: str
    description: str


ACTIVITY_SCENE_JOBS = (
    ActivitySceneJob(
        "rock_climbing",
        "Rock climbing",
        "moab_red_rocks",
        "mostly_sunny",
        "Show one helmeted climber and one belayer on a plausible dry sandstone "
        "face. Both wear harnesses and are connected by one visible climbing "
        "rope; their stance and rope system look natural and safe.",
    ),
    ActivitySceneJob(
        "paddleboarding",
        "Stand-up paddleboarding",
        "bear_lake",
        "clear",
        "Show one person standing naturally on a stand-up paddleboard near shore, "
        "wearing a personal flotation device and holding one paddle. Keep the lake "
        "calm and glassy, with no wind, whitecaps, wakes, sails, or motorboats.",
    ),
    ActivitySceneJob(
        "hammocking",
        "Hammocking",
        "mount_timpanogos",
        "partly_cloudy",
        "Show one person resting in a fabric hammock secured with straps between "
        "two sturdy living trees in the foothill foreground.",
    ),
    ActivitySceneJob(
        "skiing",
        "Cross-country skiing",
        "uinta_alpine_lake",
        "snow_showers",
        "Show one or two skiers using skis and poles on a gentle established route "
        "through continuous snow beside the alpine lake. Use practical winter "
        "clothing and avoid cliffs, avalanche terrain, and resort infrastructure.",
    ),
)

ACTIVITY_SCENES_BY_SLUG = {job.slug: job for job in ACTIVITY_SCENE_JOBS}
DRY_ACTIVITY_CONDITIONS = {"clear", "mostly_sunny", "partly_cloudy", "overcast"}
SNOW_ACTIVITY_CONDITIONS = {"snow", "snow_grains", "snow_showers"}
LAKE_ENVIRONMENTS = {"bear_lake", "uinta_alpine_lake"}
MOUNTAIN_ENVIRONMENTS = {"mount_timpanogos", "uinta_alpine_lake"}


def validate_activity_scene_jobs() -> None:
    """Reject unsafe or internally inconsistent curated activity jobs."""
    if len(ACTIVITY_SCENES_BY_SLUG) != len(ACTIVITY_SCENE_JOBS):
        raise ValueError("activity scene slugs must be unique")
    for job in ACTIVITY_SCENE_JOBS:
        if job.environment not in ENVIRONMENTS:
            raise ValueError(f"unknown environment for {job.slug}: {job.environment}")
        if job.condition not in SCENE_CONDITIONS:
            raise ValueError(f"unknown condition for {job.slug}: {job.condition}")
    paddleboarding = ACTIVITY_SCENES_BY_SLUG["paddleboarding"]
    if (
        paddleboarding.environment not in LAKE_ENVIRONMENTS
        or paddleboarding.condition not in DRY_ACTIVITY_CONDITIONS
        or paddleboarding.condition == "windy"
    ):
        raise ValueError("paddleboarding requires a dry, calm lake scene")
    skiing = ACTIVITY_SCENES_BY_SLUG["skiing"]
    if (
        skiing.environment not in MOUNTAIN_ENVIRONMENTS
        or skiing.condition not in SNOW_ACTIVITY_CONDITIONS
    ):
        raise ValueError("skiing requires a snow-covered mountain scene")


validate_activity_scene_jobs()


def build_activity_prompt(template: str, job: ActivitySceneJob) -> str:
    return (
        template.replace("{environment_name}", ENVIRONMENTS[job.environment].name)
        .replace("{weather_name}", SCENE_CONDITIONS[job.condition].name)
        .replace("{activity_name}", job.name)
        .replace("{activity_description}", job.description)
    )


def activity_scene_path(root: Path, job: ActivitySceneJob) -> Path:
    return root / job.slug / job.environment / f"{job.condition}.png"


def _selected(args: argparse.Namespace) -> list[ActivitySceneJob]:
    if args.all:
        return list(ACTIVITY_SCENE_JOBS)
    if args.activity:
        return [ACTIVITY_SCENES_BY_SLUG[slug] for slug in args.activity]
    raise ValueError("select --activity or --all")


def build_parser() -> argparse.ArgumentParser:
    package = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--activity",
        action="append",
        choices=tuple(ACTIVITY_SCENES_BY_SLUG),
        help="generate one curated activity variant; repeat for more",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="generate the four curated trials (never a Cartesian product)",
    )
    parser.add_argument("--force", action="store_true", help="replace selected activity variants")
    parser.add_argument("--dry-run", action="store_true", help="show jobs and prompts without API calls")
    parser.add_argument("--sleep", type=float, default=6.0, help="seconds between API calls")
    parser.add_argument("--gemini-key", default=load_gemini_api_key())
    parser.add_argument("--base-scenes", type=Path, default=package / "assets" / "scenes")
    parser.add_argument(
        "--prompt",
        type=Path,
        default=package / "activity_scene_prompt.template.md",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=package / "assets" / "activity_scenes",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        jobs = _selected(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.dry_run and not args.gemini_key:
        print("error: GEMINI_API_KEY required in the environment or repo .env", file=sys.stderr)
        return 2

    template = args.prompt.read_text()
    generated = skipped = failed = 0
    api_calls = 0
    for job in jobs:
        base_scene = args.base_scenes / job.environment / f"{job.condition}.png"
        output = activity_scene_path(args.out, job)
        prompt = build_activity_prompt(template, job)
        if output.exists() and not args.force:
            skipped += 1
            print(f"[skip] {job.slug}: {output}")
            continue
        if not base_scene.is_file():
            failed += 1
            print(f"[fail] {job.slug}: missing base scene {base_scene}", file=sys.stderr)
            continue
        if args.dry_run:
            print(
                f"[plan] {job.slug}: {job.environment}/{job.condition} "
                f"base={base_scene} output={output}"
            )
            print(prompt)
            continue
        if api_calls:
            time.sleep(args.sleep)
        try:
            data = call_gemini(
                args.gemini_key,
                prompt,
                style_reference=None,
                geography_reference=None,
                scene_reference=base_scene,
            )
            normalize_png(data, output)
            generated += 1
            api_calls += 1
            print(f"[ok] {job.slug}: {output} ({output.stat().st_size // 1024} KB)")
        except (OSError, RuntimeError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            failed += 1
            api_calls += 1
            print(f"[fail] {job.slug}: {exc}", file=sys.stderr)
    print(
        f"generated {generated} · skipped {skipped} · failed {failed} · "
        f"selected {len(jobs)}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
