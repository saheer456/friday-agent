from __future__ import annotations

import os
import httpx
from typing import Any, Dict, Optional

from .skill_base import BaseSkill, SkillResult, skill_action

WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 51: "Drizzle", 61: "Rain", 71: "Snow", 80: "Showers", 95: "Thunderstorm",
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

    def _fetch(self, forecast_days: int = 1) -> dict:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={self._lat}&longitude={self._lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m,relativehumidity_2m"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&timezone=auto&forecast_days={forecast_days}"
        )
        r = httpx.get(url, timeout=8.0)
        r.raise_for_status()
        return r.json()

    @skill_action(
        description="Get current weather conditions for the default location.",
        params={
            "lat": {"type": "number", "description": "Latitude (optional, defaults to configured location)."},
            "lon": {"type": "number", "description": "Longitude (optional, defaults to configured location)."},
        },
        required=[],
    )
    def get_current_weather(self, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            d = self._fetch(forecast_days=1)
            cur = d["current"]
            cond = WMO.get(cur["weathercode"], "Unknown")
            hi, lo = d["daily"]["temperature_2m_max"][0], d["daily"]["temperature_2m_min"][0]
            summary = f"{cond}, {cur['temperature_2m']}C (High {hi} / Low {lo}), Humidity {cur['relativehumidity_2m']}%, Wind {cur['windspeed_10m']} km/h"
            return SkillResult.ok(
                message="Current weather retrieved.",
                data={
                    "summary": summary, "temp_c": cur["temperature_2m"],
                    "condition": cond, "humidity": cur["relativehumidity_2m"],
                    "wind_kph": cur["windspeed_10m"], "max_c": hi, "min_c": lo,
                },
            )
        except Exception as e:
            return SkillResult.fail(f"Weather fetch failed: {e}")

    @skill_action(
        description="Get a multi-day weather forecast (today + next N days). Use this for tomorrow's weather.",
        params={
            "days": {"type": "integer", "description": "Number of forecast days (default 3, includes today)."},
            "lat": {"type": "number", "description": "Latitude (optional)."},
            "lon": {"type": "number", "description": "Longitude (optional)."},
        },
        required=[],
    )
    def get_forecast(self, days: int = 3, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            d = self._fetch(forecast_days=days)
            daily = d["daily"]
            entries = []
            for i in range(len(daily["time"])):
                entries.append({
                    "date": daily["time"][i],
                    "max_c": daily["temperature_2m_max"][i],
                    "min_c": daily["temperature_2m_min"][i],
                })
            return SkillResult.ok(
                message=f"Weather forecast for {len(entries)} days.",
                data={"forecast": entries},
            )
        except Exception as e:
            return SkillResult.fail(f"Forecast fetch failed: {e}")
