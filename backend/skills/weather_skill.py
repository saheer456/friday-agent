from __future__ import annotations

import os
import httpx
from typing import Any, Dict, Optional

from .skill_base import BaseSkill, SkillResult, skill_action

WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherSkill(BaseSkill):
    name = "weather"
    description = "Get current weather and forecasts for any location using coordinates."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._lat = float(config.get("lat", os.getenv("FRIDAY_LAT", "28.6")))
        self._lon = float(config.get("lon", os.getenv("FRIDAY_LON", "77.2")))
        self._configured = True
        return True

    def __init__(self) -> None:
        super().__init__()
        self.configure()

    async def _fetch(self, forecast_days: int = 1, lat: Optional[float] = None, lon: Optional[float] = None, location: Optional[str] = None) -> tuple[dict, Optional[str]]:
        resolved_name = None
        if location and location.strip().upper() != "DEFAULT":
            from ..tools_utils import geocode_location, CITY_ALIASES
            # Normalize alias before geocoding
            normalized_loc = CITY_ALIASES.get(location.strip().lower(), location.strip())
            res = await geocode_location(normalized_loc)
            if res:
                lat, lon, resolved_name = res
            else:
                # Return a sentinel that callers convert to SkillResult.fail
                raise ValueError(
                    f"Could not find location '{location}'"
                    + (f" (tried '{normalized_loc}')" if normalized_loc != location.strip() else "")
                    + ". Please check the spelling or try a nearby major city."
                )

        latitude = lat if lat is not None else self._lat
        longitude = lon if lon is not None else self._lon

        if latitude == 28.6 and longitude == 77.2 and not resolved_name:
            from ..tools_utils import get_profile_location, geocode_location
            ploc = get_profile_location()
            if ploc:
                res = await geocode_location(ploc)
                if res:
                    latitude, longitude, resolved_name = res[0], res[1], res[2]

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}"
            f"&current=temperature_2m,weathercode,windspeed_10m,relativehumidity_2m"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&timezone=auto&forecast_days={forecast_days}"
        )
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=8.0)
        r.raise_for_status()
        return r.json(), resolved_name

    @skill_action(
        description="Get current weather conditions for the default or a specified location.",
        params={
            "location": {"type": "string", "description": "Location name / city (optional, e.g. 'London', 'Kozhikode')."},
            "lat": {"type": "number", "description": "Latitude (optional, defaults to configured location)."},
            "lon": {"type": "number", "description": "Longitude (optional, defaults to configured location)."},
        },
        required=[],
    )
    async def get_current_weather(self, location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            d, resolved_name = await self._fetch(forecast_days=1, lat=lat, lon=lon, location=location)
            cur = d["current"]
            cond = WMO.get(cur["weathercode"], "Unknown")
            hi, lo = d["daily"]["temperature_2m_max"][0], d["daily"]["temperature_2m_min"][0]
            loc_prefix = f"{resolved_name}: " if resolved_name else ""
            summary = f"{loc_prefix}{cond}, {cur['temperature_2m']}C (High {hi} / Low {lo}), Humidity {cur['relativehumidity_2m']}%, Wind {cur['windspeed_10m']} km/h"
            return SkillResult.ok(
                message="Current weather retrieved.",
                data={
                    "summary": summary, "temp_c": cur["temperature_2m"],
                    "condition": cond, "humidity": cur["relativehumidity_2m"],
                    "wind_kph": cur["windspeed_10m"], "max_c": hi, "min_c": lo,
                    "resolved_location": resolved_name,
                },
            )
        except Exception as e:
            return SkillResult.fail(f"Weather fetch failed: {e}")

    @skill_action(
        description="Get a multi-day weather forecast (today + next N days). Use this for tomorrow's weather.",
        params={
            "days": {"type": "integer", "description": "Number of forecast days (default 3, includes today)."},
            "location": {"type": "string", "description": "Location name / city (optional, e.g. 'London', 'Kozhikode')."},
            "lat": {"type": "number", "description": "Latitude (optional)."},
            "lon": {"type": "number", "description": "Longitude (optional)."},
        },
        required=[],
    )
    async def get_forecast(self, days: int = 3, location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            d, resolved_name = await self._fetch(forecast_days=days, lat=lat, lon=lon, location=location)
            daily = d["daily"]
            entries = []
            for i in range(len(daily["time"])):
                entries.append({
                    "date": daily["time"][i],
                    "max_c": daily["temperature_2m_max"][i],
                    "min_c": daily["temperature_2m_min"][i],
                })
            return SkillResult.ok(
                message=f"Weather forecast for {len(entries)} days at {resolved_name or 'configured location'}.",
                data={"forecast": entries, "resolved_location": resolved_name},
            )
        except Exception as e:
            return SkillResult.fail(f"Forecast fetch failed: {e}")
