"""Utah environment library and complete Open-Meteo weather-art taxonomy."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .weather import Condition, DailyForecast


@dataclass(frozen=True)
class Environment:
    name: str
    description: str


@dataclass(frozen=True)
class SceneCondition:
    name: str
    description: str
    reference_mood: str


ENVIRONMENTS = {
    "mount_timpanogos": Environment(
        "Mount Timpanogos",
        "the recognizable west face of Mount Timpanogos rising above Utah Valley, "
        "with its long limestone summit ridge, folded cirques, dark conifer bands, "
        "aspen-covered foothills, and broad Wasatch scale",
    ),
    "moab_red_rocks": Environment(
        "Moab Red Rocks",
        "layered red and orange Wingate sandstone cliffs, fins and rounded domes "
    ),
    "zion_cliffs": Environment(
        "Zion National Park Cliffs",
        "towering cream, coral, and vermillion Navajo sandstone walls enclosing "
        "Zion Canyon, stepped cliff faces, dark vertical alcoves, pinyon-juniper "
        "slopes, and cottonwoods along the canyon floor",
    ),
    "uinta_alpine_lake": Environment(
        "Uinta Mountains Alpine Lake",
        "a high Uinta Mountains lake reflecting broad east-west quartzite ridges, "
        "spruce-fir forest, granite boulders, willow edges, and open alpine tundra",
    ),
    "bear_lake": Environment(
        "Bear Lake",
        "Bear Lake's luminous turquoise water, long curving shoreline, sage and "
        "aspen foreground, and softly rounded Bear River Range mountains",
    ),
}


SCENE_CONDITIONS = {
    "clear": SceneCondition(
        "Clear",
        "a crystalline clear day, open blue sky, crisp visibility, calm air, and "
        "clean warm sunlight defining the landforms",
        "sunny",
    ),
    "mostly_sunny": SceneCondition(
        "Mostly Sunny",
        "bright warm light with only a few small fair-weather clouds and soft cloud shadows",
        "sunny",
    ),
    "partly_cloudy": SceneCondition(
        "Partly Cloudy",
        "large watercolor cumulus groups alternating with blue openings and patterned light",
        "sunny",
    ),
    "overcast": SceneCondition(
        "Overcast",
        "a complete layered cloud deck, cool diffuse light, muted distance, and no hard shadows",
        "storm",
    ),
    "fog": SceneCondition(
        "Fog",
        "low cloud and fog pooled through valleys and wrapped around ridges, with "
        "landforms appearing and disappearing in pale atmospheric layers",
        "storm",
    ),
    "drizzle": SceneCondition(
        "Drizzle",
        "soft low clouds and fine barely visible drizzle, dampened colors, misty "
        "distance, and reflective wet surfaces",
        "storm",
    ),
    "rain": SceneCondition(
        "Rain",
        "layered storm clouds and visible rain curtains crossing the landscape, "
        "wet saturated color, mist between ridges, but still readable geography",
        "storm",
    ),
    "heavy_rain": SceneCondition(
        "Heavy Rain",
        "dark turbulent cloud masses, broad dense rain shafts, wet reflective "
        "foreground, deep atmospheric contrast, and localized runoff",
        "storm",
    ),
    "freezing_rain": SceneCondition(
        "Freezing Rain",
        "cold heavy cloud, rain streaks, a visible transparent ice glaze on "
        "vegetation and rock edges, and subdued blue-gray illumination",
        "snow",
    ),
    "snow": SceneCondition(
        "Snow",
        "steady snowfall, snow-covered ridges and trees, softened contours, cold "
        "indigo shadows, and a quiet low-contrast sky",
        "snow",
    ),
    "heavy_snow": SceneCondition(
        "Heavy Snow",
        "dense windless snowfall obscuring distant forms, heavily loaded trees, "
        "deep new snow, and only the strongest mountain shapes visible",
        "snow",
    ),
    "snow_grains": SceneCondition(
        "Snow Grains",
        "a cold muted scene with sparse fine granular snow, light accumulation, "
        "and flat wintry cloud",
        "snow",
    ),
    "rain_showers": SceneCondition(
        "Rain Showers",
        "broken dramatic clouds with isolated rain shafts in the distance, bright "
        "sunlit gaps, and alternating bands of wet shadow and warm light",
        "storm",
    ),
    "violent_showers": SceneCondition(
        "Violent Rain Showers",
        "towering convective clouds, intense localized rain shafts and gust fronts, "
        "while keeping the landscape recognizable",
        "storm",
    ),
    "snow_showers": SceneCondition(
        "Snow Showers",
        "broken cold clouds with localized veils of snow, intermittent pale "
        "sunlight, and patchy fresh accumulation",
        "snow",
    ),
    "thunderstorm": SceneCondition(
        "Thunderstorm",
        "deep indigo cumulonimbus, one restrained lightning branch, heavy rain "
        "curtains, wind-driven mist, and a dramatic illuminated storm edge",
        "storm",
    ),
    "hail_thunderstorm": SceneCondition(
        "Thunderstorm with Hail",
        "severe dark storm clouds, rain and pale hail streaks, a distant lightning "
        "flash, turbulent sky, and temporary white hail accumulation",
        "storm",
    ),
    "windy": SceneCondition(
        "Windy",
        "long wind-swept cloud strokes, visibly bent grasses and trees, airborne "
        "dust or snow where appropriate, and strong directional movement",
        "storm",
    ),
    "hot_dry": SceneCondition(
        "Hot and Dry",
        "hard brilliant summer light, sparse high clouds, heat-softened distance, "
        "dry foreground color, and high contrast without an orange color cast",
        "sunny",
    ),
    "melting_snow": SceneCondition(
        "Melting Snow",
        "broken retreating snowfields, dark wet rock, visible rivulets, saturated "
        "spring vegetation, and warm sunlight under a cool sky",
        "snow",
    ),
    "virga": SceneCondition(
        "Virga",
        "high-based clouds with graceful precipitation shafts evaporating before "
        "they reach the ground, dry foreground, and distant atmospheric drama",
        "storm",
    ),
}


def condition_slug_for_forecast(forecast: DailyForecast) -> str:
    code = forecast.weather_code
    if forecast.condition == Condition.SNOW and forecast.high_c > 2:
        return "melting_snow"
    if forecast.high_c >= 30 and forecast.precipitation_mm < 1 and forecast.cloud_cover_mean < 45:
        return "hot_dry"
    if (
        forecast.precipitation_probability >= 30
        and 0 < forecast.precipitation_mm < 0.5
        and code not in (56, 57, 66, 67)
    ):
        return "virga"
    if (
        (forecast.wind_speed_max_kmh >= 30 or forecast.wind_gust_max_kmh >= 45)
        and code in (0, 1, 2, 3)
    ):
        return "windy"
    if code == 0:
        return "clear"
    if code == 1:
        return "mostly_sunny"
    if code == 2:
        return "partly_cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55):
        return "drizzle"
    if code in (56, 57):
        return "freezing_drizzle"
    if code in (61, 63):
        return "rain"
    if code == 65:
        return "heavy_rain"
    if code in (66, 67):
        return "freezing_rain"
    if code in (71, 73):
        return "snow"
    if code == 75:
        return "heavy_snow"
    if code == 77:
        return "snow_grains"
    if code in (80, 81):
        return "rain_showers"
    if code == 82:
        return "violent_showers"
    if code in (85, 86):
        return "snow_showers"
    if code == 95:
        return "thunderstorm"
    if code in (96, 99):
        return "hail_thunderstorm"
    return "partly_cloudy"


def choose_environment(forecast: DailyForecast, configured: str = "auto") -> str:
    if configured != "auto":
        if configured not in ENVIRONMENTS:
            raise ValueError(f"unknown environment {configured!r}")
        return configured
    identity = (forecast.date.isoformat(), round(forecast.latitude, 3), round(forecast.longitude, 3))
    names = tuple(ENVIRONMENTS)
    index = int.from_bytes(hashlib.sha256(repr(identity).encode()).digest()[:8], "big") % len(names)
    return names[index]


def generated_scene_path(
    forecast: DailyForecast,
    configured: str = "auto",
    root: Path | None = None,
) -> tuple[str, str, Path]:
    root = root or Path(__file__).parent / "assets" / "scenes"
    condition = condition_slug_for_forecast(forecast)
    if configured == "auto":
        candidates = [
            environment for environment in ENVIRONMENTS
            if (root / environment / f"{condition}.png").is_file()
        ]
        if candidates:
            identity = (
                forecast.date.isoformat(),
                round(forecast.latitude, 3),
                round(forecast.longitude, 3),
                condition,
            )
            index = int.from_bytes(hashlib.sha256(repr(identity).encode()).digest()[:8], "big") % len(candidates)
            environment = candidates[index]
        else:
            environment = choose_environment(forecast, configured)
    else:
        environment = choose_environment(forecast, configured)
    return environment, condition, root / environment / f"{condition}.png"
