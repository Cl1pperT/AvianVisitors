"""Configuration and execution flow for the weather frame."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from frame import display as panel

from .eink import apply_blue_bias, quantize_spectra6
from .activities import recommend_activities
from .generate_scenes import generate_daily_scene
from .renderer import STYLES, render_forecast
from .scene_catalog import ENVIRONMENTS
from .weather import DailyForecast, ForecastProvider, OpenMeteoProvider

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib


DEFAULTS: dict[str, Any] = {
    "provider": "open_meteo",
    "location": "",
    "country_code": "",
    "location_label": "",
    "units": "imperial",
    "style": "woodblock",
    "caption": False,
    "scene_source": "auto",
    "environment": "auto",
    "output": "~/.weatherframe/weather.png",
    "state": "~/.weatherframe/state.json",
    "timeout": 30,
    "quiet_start": 22,
    "quiet_end": 6,
    "heal_hours": 24,
    "rotate": 90,
    "saturation": 0.6,
    "blue_bias": 0.5,
    "panel": "",
    "gemini_key": "",
}


def load_config(path: str) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    with open(os.path.expanduser(path), "rb") as handle:
        cfg.update(tomllib.load(handle))
    validate_config(cfg)
    return cfg


def validate_config(cfg: Mapping[str, Any]) -> None:
    if cfg.get("provider") != "open_meteo":
        raise ValueError("provider must be 'open_meteo' in this milestone")
    if not str(cfg.get("location") or "").strip():
        raise ValueError("config must set a city or postal code in location")
    if cfg.get("units") not in ("imperial", "metric"):
        raise ValueError("units must be 'imperial' or 'metric'")
    if cfg.get("style") not in STYLES:
        raise ValueError("style must be 'woodblock' or 'ink_wash'")
    if cfg.get("scene_source") not in ("auto", "generated", "procedural", "ai"):
        raise ValueError("scene_source must be 'auto', 'generated', 'procedural', or 'ai'")
    if cfg.get("environment") != "auto" and cfg.get("environment") not in ENVIRONMENTS:
        raise ValueError("environment must be 'auto' or a known environment slug")
    if not isinstance(cfg.get("caption"), bool):
        raise ValueError("caption must be true or false")
    if int(cfg.get("rotate", 0)) not in (90, 270):
        raise ValueError("rotate must be 90 or 270")
    if not 0 <= float(cfg.get("saturation", -1)) <= 1:
        raise ValueError("saturation must be between 0 and 1")
    if not 0 <= float(cfg.get("blue_bias", -1)) <= 1:
        raise ValueError("blue_bias must be between 0 and 1")
    for key in ("quiet_start", "quiet_end"):
        if not 0 <= int(cfg.get(key, -1)) <= 23:
            raise ValueError(f"{key} must be an hour from 0 through 23")
    if float(cfg.get("heal_hours", 0)) <= 0:
        raise ValueError("heal_hours must be greater than zero")
    if float(cfg.get("timeout", 0)) <= 0:
        raise ValueError("timeout must be greater than zero")


def provider_for_config(cfg: Mapping[str, Any]) -> ForecastProvider:
    if cfg["provider"] == "open_meteo":
        return OpenMeteoProvider()
    raise ValueError(f"unsupported provider {cfg['provider']!r}")


def fetch_forecast(cfg: Mapping[str, Any], provider: ForecastProvider | None = None) -> DailyForecast:
    provider = provider or provider_for_config(cfg)
    forecast = provider.fetch_today(
        str(cfg["location"]),
        country_code=str(cfg.get("country_code") or ""),
        location_label=str(cfg.get("location_label") or ""),
        timeout=float(cfg["timeout"]),
    )
    print(
        f"forecast: {forecast.location_name} "
        f"({forecast.latitude:.3f}, {forecast.longitude:.3f}), {forecast.date}"
    )
    return forecast


def _save_png(image: Image.Image, path: str) -> str:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = path + ".tmp"
    image.save(temporary, format="PNG")
    os.replace(temporary, path)
    return path


def image_signature(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(f"{image.mode}:{image.size[0]}x{image.size[1]}".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()[:24]


def _local_now(forecast: DailyForecast, now: datetime | None) -> datetime:
    try:
        timezone = ZoneInfo(forecast.timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"unknown forecast timezone {forecast.timezone!r}") from exc
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone)
    return now.astimezone(timezone)


def create_artwork(
    cfg: Mapping[str, Any],
    forecast: DailyForecast,
    *,
    ai_generator=generate_daily_scene,
) -> tuple[Image.Image, tuple[str, ...]]:
    """Render artwork, using season recommendations for live AI generation."""
    scene_source = str(cfg["scene_source"])
    activities: tuple[str, ...] = ()
    scene_image = None
    if scene_source == "ai":
        activities = recommend_activities(forecast, limit=5)
        print(f"activity candidates: {', '.join(activities)}")
        api_key = str(cfg.get("gemini_key") or os.environ.get("GEMINI_API_KEY") or "")
        if not api_key:
            raise RuntimeError(
                "scene_source 'ai' requires GEMINI_API_KEY or gemini_key in config"
            )
        scene_image = ai_generator(
            forecast,
            activities,
            api_key=api_key,
            environment=str(cfg["environment"]),
        )
    image = render_forecast(
        forecast,
        style=str(cfg["style"]),
        caption=bool(cfg["caption"]),
        units=str(cfg["units"]),
        scene_source=scene_source,
        environment=str(cfg["environment"]),
        scene_image=scene_image,
    )
    return image, activities


def run(
    cfg: Mapping[str, Any],
    *,
    preview: str | None = None,
    display: bool = False,
    force: bool = False,
    provider: ForecastProvider | None = None,
    panel_module=panel,
    now: datetime | None = None,
    ai_generator=generate_daily_scene,
) -> str:
    """Render a forecast and optionally preview or push it.

    Returns one of ``preview``, ``rendered``, ``updated``, ``quiet``, or
    ``unchanged``. Preview mode never writes the configured output or state.
    """
    validate_config(cfg)
    if preview and display:
        raise ValueError("preview and display modes are mutually exclusive")

    forecast = fetch_forecast(cfg, provider)
    image, _activities = create_artwork(
        cfg, forecast, ai_generator=ai_generator
    )
    image = apply_blue_bias(
        image,
        amount=float(cfg["blue_bias"]),
        saturation=float(cfg["saturation"]),
    )

    if preview:
        output = quantize_spectra6(image, float(cfg["saturation"]))
        path = _save_png(output, preview)
        print(f"wrote preview {path}")
        return "preview"

    output_path = _save_png(image, str(cfg["output"]))
    print(f"wrote artwork {output_path}")
    if not display:
        return "rendered"

    local_now = _local_now(forecast, now)
    state = panel_module.load_state(str(cfg["state"]))
    quantized = quantize_spectra6(image, float(cfg["saturation"]))
    signature = image_signature(quantized)
    last_refresh = float(state.get("last_refresh") or 0)
    heal_due = local_now.timestamp() - last_refresh >= float(cfg["heal_hours"]) * 3600

    if not force:
        if panel_module.in_quiet_hours(cfg, local_now.hour):
            print("quiet hours; panel unchanged")
            return "quiet"
        if signature == state.get("signature") and not heal_due:
            print("image unchanged; panel unchanged")
            return "unchanged"

    rotate = int(cfg["rotate"])
    # frame.display accepts a portrait source and rotates it into the panel's
    # native 1600x1200 buffer. Weather artwork is already native landscape, so
    # pre-rotate it in the opposite direction and let the proven hardware path
    # restore it without resizing or distortion.
    portrait_source = image.rotate((360 - rotate) % 360, expand=True)
    panel_module.push_panel(
        portrait_source,
        rotate,
        float(cfg["saturation"]),
        str(cfg.get("panel") or ""),
    )
    panel_module.save_state(str(cfg["state"]), signature, local_now.timestamp())
    print("panel updated")
    return "updated"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate procedural daily weather artwork for the AvianVisitors e-ink frame."
    )
    parser.add_argument(
        "--config",
        default="~/.weatherframe/config.toml",
        help="TOML configuration path (default: ~/.weatherframe/config.toml)",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preview", metavar="PNG", help="write a Spectra-6 preview; never touch hardware")
    modes.add_argument("--display", action="store_true", help="explicitly update the physical e-ink panel")
    parser.add_argument("--force", action="store_true", help="with --display, bypass quiet hours and signature checks")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        run(cfg, preview=args.preview, display=args.display, force=args.force)
    except Exception as exc:
        print(f"weather frame failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
