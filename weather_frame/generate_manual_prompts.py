"""Build a copy-paste prompt pack for manual generation in ChatGPT Images."""
from __future__ import annotations

import argparse
from pathlib import Path

from .generate_scenes import (
    _default_styles,
    build_prompt,
    discover_style_references,
    select_style_reference,
)
from .scene_catalog import ENVIRONMENTS, SCENE_CONDITIONS


# One manual prompt for every active weather condition, distributed across the
# active environments.
PROMPT_JOBS = {
    "mount_timpanogos": (
        "clear", "mostly_sunny", "snow", "thunderstorm", "melting_snow",
    ),
    "moab_red_rocks": ("hot_dry", "virga", "rain_showers", "windy"),
    "zion_cliffs": ("partly_cloudy", "rain", "heavy_rain", "violent_showers"),
    "uinta_alpine_lake": (
        "overcast", "freezing_rain", "heavy_snow", "snow_grains", "snow_showers",
    ),
    "bear_lake": ("fog", "drizzle", "hail_thunderstorm"),
}


def render_pack(template: str, style_directory: Path) -> str:
    references = discover_style_references(style_directory)
    lines = [
        "# Manual ChatGPT Weather Image Prompt Pack",
        "",
        "These prompts are for ChatGPT Images with a Plus subscription. For each",
        "entry, upload the listed Goal Image as the style reference, copy the",
        "entire prompt block into ChatGPT, select a **4:3 landscape** aspect",
        "ratio, then download the result to the listed destination path.",
        "",
        "Do not upload all three Goal Images for one request. The selected sunny,",
        "snow, or storm reference gives ChatGPT a clearer style and weather target.",
        "",
    ]
    number = 0
    for environment, conditions in PROMPT_JOBS.items():
        place = ENVIRONMENTS[environment]
        for condition in conditions:
            number += 1
            weather = SCENE_CONDITIONS[condition]
            reference = select_style_reference(condition, references)
            reference_name = reference.name if reference else "(no reference found)"
            destination = f"weather_frame/assets/scenes/{environment}/{condition}.png"
            prompt = build_prompt(template, environment, condition)
            lines.extend(
                [
                    f"## {number:02d}. {place.name} — {weather.name}",
                    "",
                    f"- Upload: `goalimages/{reference_name}`",
                    f"- Save result as: `{destination}`",
                    "",
                    "```text",
                    prompt.rstrip(),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--styles", type=Path, default=_default_styles())
    parser.add_argument(
        "--prompt",
        type=Path,
        default=Path(__file__).parent / "scene_prompt.template.md",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "manual_prompt_pack.md",
    )
    args = parser.parse_args(argv)
    content = render_pack(args.prompt.read_text(), args.styles)
    args.out.write_text(content)
    print(f"wrote {sum(len(items) for items in PROMPT_JOBS.values())} prompts to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
