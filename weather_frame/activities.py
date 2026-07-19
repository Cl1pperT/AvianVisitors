"""Adapter between a weather-frame forecast and the sibling season package."""
from __future__ import annotations

import sys
from pathlib import Path

from .weather import DailyForecast


def _load_season():
    """Load the sibling package in both the source checkout and installed layouts."""
    try:
        from season import WeatherForecast, rank_activities
    except ModuleNotFoundError as exc:
        workspace = Path(__file__).resolve().parents[2]
        if (workspace / "season" / "__init__.py").is_file():
            sys.path.insert(0, str(workspace))
            from season import WeatherForecast, rank_activities
        else:
            raise RuntimeError(
                "the season package must be installed or checked out beside AvianVisitors"
            ) from exc
    return WeatherForecast, rank_activities


def recommend_activities(forecast: DailyForecast, limit: int = 5) -> tuple[str, ...]:
    """Return the top weather-appropriate activity names for today's forecast."""
    WeatherForecast, rank_activities = _load_season()
    high_f = forecast.high_c * 9 / 5 + 32
    feels_like_c = (
        forecast.apparent_temperature_max_c
        if forecast.apparent_temperature_max_c is not None
        else forecast.high_c
    )
    snowpack_inches = (
        forecast.snow_depth_m * 39.3701
        if forecast.snow_depth_m is not None
        else forecast.snowfall_cm / 2.54
    )
    season_forecast = WeatherForecast(
        temperature_f=round(high_f),
        low_temperature_f=round(forecast.low_c * 9 / 5 + 32),
        feels_like_f=round(feels_like_c * 9 / 5 + 32),
        precipitation_chance=forecast.precipitation_probability,
        precipitation_inches=forecast.precipitation_mm / 25.4,
        snowpack_inches=snowpack_inches,
        uv_index=round(forecast.uv_index_max if forecast.uv_index_max is not None else 5),
        wind_mph=round(forecast.wind_speed_max_kmh / 1.609344),
        humidity_percent=round(
            forecast.humidity_mean_percent
            if forecast.humidity_mean_percent is not None
            else 50
        ),
        cloud_cover_percent=round(forecast.cloud_cover_mean),
        visibility_miles=(
            forecast.visibility_mean_m / 1609.344
            if forecast.visibility_mean_m is not None
            else 10.0
        ),
        air_quality_index=forecast.air_quality_index or 50,
        day_of_year=forecast.date.timetuple().tm_yday,
    )
    return tuple(result.activity for result in rank_activities(season_forecast)[:limit])
