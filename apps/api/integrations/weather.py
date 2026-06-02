"""Weather for Bo's home location. Read-only.

Keyed by WEATHER_API_KEY + HOME_LAT/HOME_LON. Unconfigured → not-connected.
"""
from __future__ import annotations

from .base import IntegrationResult, env, http_get_json, not_connected, ok, safe

SOURCE = "weather"
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


def _config() -> tuple[str, str, str]:
    return env("WEATHER_API_KEY"), env("HOME_LAT"), env("HOME_LON")


def status() -> IntegrationResult:
    key, lat, lon = _config()
    if not key or not lat or not lon:
        return not_connected(SOURCE, "WEATHER_API_KEY / HOME_LAT / HOME_LON not set")
    return ok(SOURCE, {"lat": lat, "lon": lon})


@safe(SOURCE)
def get_current() -> IntegrationResult:
    key, lat, lon = _config()
    if not key or not lat or not lon:
        return not_connected(SOURCE, "WEATHER_API_KEY / HOME_LAT / HOME_LON not set")
    raw = http_get_json(
        BASE_URL, params={"lat": lat, "lon": lon, "appid": key, "units": "imperial"}
    )
    weather = (raw.get("weather") or [{}])[0] if isinstance(raw, dict) else {}
    main = raw.get("main", {}) if isinstance(raw, dict) else {}
    return ok(
        SOURCE,
        {
            "temp": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "conditions": weather.get("main"),
            "description": weather.get("description"),
            "humidity": main.get("humidity"),
            "location": raw.get("name") if isinstance(raw, dict) else None,
        },
    )
