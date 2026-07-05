"""Weather-provider boundary and Open-Meteo implementation."""
from __future__ import annotations

import json
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "AvianVisitors-weather-frame/1.0"

DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "sunrise",
    "sunset",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
)
HOURLY_FIELDS = (
    "weather_code",
    "cloud_cover",
    "precipitation_probability",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "wind_direction_10m",
)


class Condition(str, Enum):
    CLEAR = "clear"
    CLOUDY = "cloudy"
    FOG = "fog"
    RAIN = "rain"
    SNOW = "snow"
    THUNDER = "thunder"


class PrecipitationPeriod(str, Enum):
    NONE = "none"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


@dataclass(frozen=True)
class ResolvedLocation:
    name: str
    latitude: float
    longitude: float
    timezone: str
    country_code: str = ""
    admin1: str = ""


@dataclass(frozen=True)
class DailyForecast:
    date: date
    timezone: str
    location_name: str
    latitude: float
    longitude: float
    weather_code: int
    condition: Condition
    high_c: float
    low_c: float
    precipitation_probability: int
    precipitation_mm: float
    rain_mm: float
    snowfall_cm: float
    cloud_cover_mean: float
    wind_speed_max_kmh: float
    wind_gust_max_kmh: float
    wind_direction_deg: float
    sunrise: datetime
    sunset: datetime
    precipitation_period: PrecipitationPeriod


class ForecastProvider(Protocol):
    def fetch_today(
        self,
        location: str,
        *,
        country_code: str = "",
        location_label: str = "",
        timeout: float = 30,
    ) -> DailyForecast:
        """Resolve a location and return its local forecast for today."""


Transport = Callable[[str, float], Mapping[str, Any]]


def condition_for_code(code: int) -> Condition:
    if code in (95, 96, 99):
        return Condition.THUNDER
    if code in (71, 73, 75, 77, 85, 86):
        return Condition.SNOW
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return Condition.RAIN
    if code in (45, 48):
        return Condition.FOG
    if code in (2, 3):
        return Condition.CLOUDY
    return Condition.CLEAR


def _default_transport(url: str, timeout: float) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(2_000_000)
    except Exception as exc:
        raise RuntimeError(f"Open-Meteo request failed: {exc}") from exc
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Open-Meteo returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Open-Meteo returned an unexpected response")
    if data.get("error"):
        raise RuntimeError(f"Open-Meteo error: {data.get('reason', 'unknown error')}")
    return data


def _url(base: str, params: Mapping[str, Any]) -> str:
    return base + "?" + urllib.parse.urlencode(params)


def _first(mapping: Mapping[str, Any], key: str) -> Any:
    values = mapping.get(key)
    if not isinstance(values, list) or not values or values[0] is None:
        raise RuntimeError(f"forecast response is missing daily.{key}")
    return values[0]


def _float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"forecast response has invalid {name}") from exc


def _hour_period(hour: int) -> PrecipitationPeriod:
    if hour < 12:
        return PrecipitationPeriod.MORNING
    if hour < 18:
        return PrecipitationPeriod.AFTERNOON
    return PrecipitationPeriod.EVENING


def _precipitation_period(hourly: Mapping[str, Any]) -> PrecipitationPeriod:
    times = hourly.get("time")
    probabilities = hourly.get("precipitation_probability")
    amounts = hourly.get("precipitation")
    codes = hourly.get("weather_code")
    if not all(isinstance(values, list) for values in (times, probabilities, amounts, codes)):
        return PrecipitationPeriod.NONE

    scores = {
        PrecipitationPeriod.MORNING: 0.0,
        PrecipitationPeriod.AFTERNOON: 0.0,
        PrecipitationPeriod.EVENING: 0.0,
    }
    evidence = False
    for raw_time, raw_probability, raw_amount, raw_code in zip(times, probabilities, amounts, codes):
        try:
            hour = datetime.fromisoformat(str(raw_time)).hour
            probability = float(raw_probability or 0)
            amount = float(raw_amount or 0)
            condition = condition_for_code(int(raw_code or 0))
        except (TypeError, ValueError):
            continue
        precip_code = condition in (Condition.RAIN, Condition.SNOW, Condition.THUNDER)
        if amount > 0 or probability >= 20 or precip_code:
            evidence = True
        period = _hour_period(hour)
        scores[period] = max(scores[period], probability + amount * 12 + (15 if precip_code else 0))
    if not evidence:
        return PrecipitationPeriod.NONE
    return max(scores, key=scores.get)


def _mean_hourly(hourly: Mapping[str, Any], key: str) -> float:
    values = hourly.get(key)
    if not isinstance(values, list):
        raise RuntimeError(f"forecast response is missing hourly.{key}")
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        raise RuntimeError(f"forecast response has no hourly.{key} values")
    return float(statistics.fmean(numbers))


def parse_open_meteo_forecast(
    payload: Mapping[str, Any],
    resolved: ResolvedLocation,
    *,
    location_label: str = "",
) -> DailyForecast:
    daily = payload.get("daily")
    hourly = payload.get("hourly")
    if not isinstance(daily, dict) or not isinstance(hourly, dict):
        raise RuntimeError("forecast response is missing daily or hourly data")

    weather_code = int(_first(daily, "weather_code"))
    forecast_date = date.fromisoformat(str(_first(daily, "time")))
    sunrise = datetime.fromisoformat(str(_first(daily, "sunrise")))
    sunset = datetime.fromisoformat(str(_first(daily, "sunset")))
    timezone = str(payload.get("timezone") or resolved.timezone)
    if not timezone:
        raise RuntimeError("forecast response is missing timezone")

    return DailyForecast(
        date=forecast_date,
        timezone=timezone,
        location_name=location_label or resolved.name,
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        weather_code=weather_code,
        condition=condition_for_code(weather_code),
        high_c=_float(_first(daily, "temperature_2m_max"), "temperature maximum"),
        low_c=_float(_first(daily, "temperature_2m_min"), "temperature minimum"),
        precipitation_probability=round(
            _float(_first(daily, "precipitation_probability_max"), "precipitation probability")
        ),
        precipitation_mm=_float(_first(daily, "precipitation_sum"), "precipitation sum"),
        rain_mm=_float(_first(daily, "rain_sum"), "rain sum"),
        snowfall_cm=_float(_first(daily, "snowfall_sum"), "snowfall sum"),
        cloud_cover_mean=_mean_hourly(hourly, "cloud_cover"),
        wind_speed_max_kmh=_float(_first(daily, "wind_speed_10m_max"), "maximum wind speed"),
        wind_gust_max_kmh=_float(_first(daily, "wind_gusts_10m_max"), "maximum wind gust"),
        wind_direction_deg=_float(
            _first(daily, "wind_direction_10m_dominant"), "dominant wind direction"
        )
        % 360,
        sunrise=sunrise,
        sunset=sunset,
        precipitation_period=_precipitation_period(hourly),
    )


class OpenMeteoProvider:
    """Open-Meteo geocoding and forecast provider."""

    def __init__(self, transport: Transport | None = None):
        self._transport = transport or _default_transport

    def resolve(self, location: str, country_code: str = "", timeout: float = 30) -> ResolvedLocation:
        def search(term: str, count: int = 1):
            params: dict[str, Any] = {
                "name": term,
                "count": count,
                "language": "en",
                "format": "json",
            }
            if country_code:
                params["countryCode"] = country_code.upper()
            return self._transport(_url(GEOCODING_URL, params), timeout).get("results")

        results = search(location)
        # Open-Meteo often treats a comma-delimited "City, Region" as no match.
        # Retry the city portion while retaining the country filter. The selected
        # canonical name and coordinates are logged by app.fetch_forecast so an
        # unexpected first match is visible before a panel is enabled.
        if (not isinstance(results, list) or not results) and "," in location:
            city = location.split(",", 1)[0].strip()
            if city:
                results = search(city, count=10)
        if not isinstance(results, list) or not results:
            suffix = f" in {country_code.upper()}" if country_code else ""
            raise RuntimeError(f"Open-Meteo found no location for {location!r}{suffix}")
        result = results[0]
        if not isinstance(result, dict):
            raise RuntimeError("Open-Meteo returned an invalid geocoding result")
        try:
            name = str(result["name"])
            admin1 = str(result.get("admin1") or "")
            country = str(result.get("country_code") or "")
            display_name = ", ".join(part for part in (name, admin1) if part)
            return ResolvedLocation(
                name=display_name,
                latitude=float(result["latitude"]),
                longitude=float(result["longitude"]),
                timezone=str(result.get("timezone") or "auto"),
                country_code=country,
                admin1=admin1,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Open-Meteo returned an incomplete geocoding result") from exc

    def fetch_today(
        self,
        location: str,
        *,
        country_code: str = "",
        location_label: str = "",
        timeout: float = 30,
    ) -> DailyForecast:
        resolved = self.resolve(location, country_code=country_code, timeout=timeout)
        params = {
            "latitude": resolved.latitude,
            "longitude": resolved.longitude,
            "timezone": "auto",
            "forecast_days": 1,
            "daily": ",".join(DAILY_FIELDS),
            "hourly": ",".join(HOURLY_FIELDS),
        }
        payload = self._transport(_url(FORECAST_URL, params), timeout)
        return parse_open_meteo_forecast(payload, resolved, location_label=location_label)
