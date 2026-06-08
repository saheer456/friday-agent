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
    description = "Get current weather, hourly forecast, and air quality information."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._lat = float(config.get("lat", os.getenv("FRIDAY_LAT", "28.6")))
        self._lon = float(config.get("lon", os.getenv("FRIDAY_LON", "77.2")))
        self._configured = True
        return True

    def __init__(self) -> None:
        super().__init__()
        self.configure()
        self._weather_client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._weather_client is None:
            self._weather_client = httpx.AsyncClient(timeout=8.0)
        return self._weather_client

    async def health_check(self) -> bool:
        try:
            r = await self._get_client().get("https://geocoding-api.open-meteo.com/v1/search?name=London&count=1", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    async def _resolve_coords(self, location: Optional[str], lat: Optional[float], lon: Optional[float]) -> tuple[float, float, str | None]:
        resolved_name = None
        if location and location.strip().upper() != "DEFAULT":
            from ..tools_utils import geocode_location, CITY_ALIASES
            normalized_loc = CITY_ALIASES.get(location.strip().lower(), location.strip())
            res = await geocode_location(normalized_loc)
            if res:
                lat, lon, resolved_name = res
            else:
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

        return latitude, longitude, resolved_name

    async def _fetch(self, forecast_days: int = 1, lat: Optional[float] = None, lon: Optional[float] = None, location: Optional[str] = None) -> dict:
        latitude, longitude, resolved_name = await self._resolve_coords(location, lat, lon)
        data = None
        backend = None

        if forecast_days <= 3:
            try:
                wttr_url = f"https://wttr.in/{latitude},{longitude}?format=j1"
                client = self._get_client()
                r = await client.get(wttr_url, timeout=5.0)
                if r.status_code == 200:
                    data = r.json()
                    backend = "wttr.in"
            except Exception:
                pass

        if not data:
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={latitude}&longitude={longitude}"
                f"&current=temperature_2m,weathercode,windspeed_10m,relativehumidity_2m"
                f"&daily=temperature_2m_max,temperature_2m_min"
                f"&timezone=auto&forecast_days={forecast_days}"
            )
            client = self._get_client()
            r = await client.get(url, timeout=8.0)
            r.raise_for_status()
            data = r.json()
            backend = "open-meteo"

        timezone_resp = data.get("timezone", "auto")

        if backend == "wttr.in":
            current_cond = data["current_condition"][0]
            temp_c = float(current_cond["temp_C"])
            condition = current_cond["weatherDesc"][0]["value"]
            humidity = int(current_cond["humidity"])
            wind_kph = float(current_cond["windspeedKmph"])

            today_weather = data["weather"][0]
            max_c = float(today_weather["maxtempC"])
            min_c = float(today_weather["mintempC"])

            forecast = []
            for w in data["weather"][:forecast_days]:
                forecast.append({
                    "date": w["date"],
                    "max_c": float(w["maxtempC"]),
                    "min_c": float(w["mintempC"])
                })
        else:
            cur = data["current"]
            temp_c = float(cur["temperature_2m"])
            w_code = cur.get("weathercode", cur.get("weather_code", 0))
            condition = WMO.get(w_code, "Unknown")
            humidity = int(cur.get("relativehumidity_2m", cur.get("relative_humidity_2m", 0)))
            wind_kph = float(cur.get("windspeed_10m", cur.get("wind_speed_10m", 0)))

            daily = data["daily"]
            max_c = float(daily["temperature_2m_max"][0])
            min_c = float(daily["temperature_2m_min"][0])

            forecast = []
            for i in range(len(daily["time"])):
                forecast.append({
                    "date": daily["time"][i],
                    "max_c": float(daily["temperature_2m_max"][i]),
                    "min_c": float(daily["temperature_2m_min"][i])
                })

        return {
            "backend": backend,
            "resolved_location": resolved_name,
            "temp_c": temp_c,
            "condition": condition,
            "humidity": humidity,
            "wind_kph": wind_kph,
            "max_c": max_c,
            "min_c": min_c,
            "forecast": forecast,
            "timezone": timezone_resp
        }

    @skill_action(
        description="Get current weather conditions for the default or a specified location.",
        params={
            "location": {"type": "string", "description": "Location name / city (optional, e.g. 'London', 'Kozhikode')."},
            "lat": {"type": "number", "description": "Latitude (optional)."},
            "lon": {"type": "number", "description": "Longitude (optional)."},
        },
        required=[],
        permissions=["weather:read"]
    )
    async def get_current_weather(self, location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            parsed = await self._fetch(forecast_days=1, lat=lat, lon=lon, location=location)
            resolved_name = parsed["resolved_location"]
            loc_prefix = f"{resolved_name}: " if resolved_name else ""
            summary = f"{loc_prefix}{parsed['condition']}, {parsed['temp_c']}°C (High {parsed['max_c']} / Low {parsed['min_c']}), Humidity {parsed['humidity']}%, Wind {parsed['wind_kph']} km/h"
            return SkillResult.ok(
                message="Current weather retrieved.",
                data={
                    "summary": summary,
                    "temp_c": parsed["temp_c"],
                    "condition": parsed["condition"],
                    "humidity": parsed["humidity"],
                    "wind_kph": parsed["wind_kph"],
                    "max_c": parsed["max_c"],
                    "min_c": parsed["min_c"],
                    "resolved_location": resolved_name,
                    "timezone": parsed["timezone"],
                    "backend": parsed["backend"]
                },
            )
        except Exception as e:
            return SkillResult.fail(f"Weather fetch failed: {e}")

    @skill_action(
        description="Get a multi-day weather forecast (today + next N days).",
        params={
            "days": {"type": "integer", "description": "Number of forecast days (default 3, includes today)."},
            "location": {"type": "string", "description": "Location name / city (optional)."},
            "lat": {"type": "number", "description": "Latitude (optional)."},
            "lon": {"type": "number", "description": "Longitude (optional)."},
        },
        required=[],
        permissions=["weather:read"]
    )
    async def get_forecast(self, days: int = 3, location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            parsed = await self._fetch(forecast_days=days, lat=lat, lon=lon, location=location)
            resolved_name = parsed["resolved_location"]
            return SkillResult.ok(
                message=f"Weather forecast for {len(parsed['forecast'])} days at {resolved_name or 'configured location'}.",
                data={
                    "forecast": parsed["forecast"],
                    "resolved_location": resolved_name,
                    "timezone": parsed["timezone"],
                    "backend": parsed["backend"]
                },
            )
        except Exception as e:
            return SkillResult.fail(f"Forecast fetch failed: {e}")

    @skill_action(
        description="Get hourly weather forecast (temperature, humidity, condition) for the next N hours.",
        params={
            "location": {"type": "string", "description": "Location name / city (optional)."},
            "lat": {"type": "number", "description": "Latitude (optional)."},
            "lon": {"type": "number", "description": "Longitude (optional)."},
            "hours": {"type": "integer", "description": "Number of hours to return (default 24)."},
        },
        required=[],
        permissions=["weather:read"]
    )
    async def get_hourly_forecast(self, location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None, hours: int = 24) -> SkillResult:
        try:
            latitude, longitude, resolved_name = await self._resolve_coords(location, lat, lon)
            url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=temperature_2m,relativehumidity_2m,weathercode&timezone=auto&forecast_days=2"
            
            client = self._get_client()
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            
            hourly = data["hourly"]
            timezone_resp = data.get("timezone", "auto")
            
            hours_data = []
            for i in range(min(hours, len(hourly["time"]))):
                w_code = hourly["weathercode"][i]
                cond = WMO.get(w_code, "Unknown")
                hours_data.append({
                    "time": hourly["time"][i],
                    "temp_c": hourly["temperature_2m"][i],
                    "humidity": hourly["relativehumidity_2m"][i],
                    "condition": cond
                })
            
            return SkillResult.ok(
                message=f"Hourly forecast retrieved for {resolved_name or 'configured location'}.",
                data={
                    "resolved_location": resolved_name,
                    "timezone": timezone_resp,
                    "hourly": hours_data
                }
            )
        except Exception as e:
            return SkillResult.fail(f"Hourly forecast fetch failed: {e}")

    @skill_action(
        description="Get current air quality indexes (AQI, PM2.5, PM10, CO, NO2, SO2, O3) for a location.",
        params={
            "location": {"type": "string", "description": "Location name / city (optional)."},
            "lat": {"type": "number", "description": "Latitude (optional)."},
            "lon": {"type": "number", "description": "Longitude (optional)."},
        },
        required=[],
        permissions=["weather:read"]
    )
    async def get_air_quality(self, location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None) -> SkillResult:
        try:
            latitude, longitude, resolved_name = await self._resolve_coords(location, lat, lon)
            url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={latitude}&longitude={longitude}&current=pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,us_aqi&timezone=auto"
            
            client = self._get_client()
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            
            cur = data["current"]
            aqi = cur.get("us_aqi")
            
            if aqi is None:
                category = "Unknown"
            elif aqi <= 50:
                category = "Good (Little to no risk)"
            elif aqi <= 100:
                category = "Moderate (Acceptable)"
            elif aqi <= 150:
                category = "Unhealthy for Sensitive Groups"
            elif aqi <= 200:
                category = "Unhealthy"
            elif aqi <= 300:
                category = "Very Unhealthy (Health alert)"
            else:
                category = "Hazardous (Health warning)"
            
            summary = (
                f"Air Quality at {resolved_name or 'configured location'}: AQI {aqi} ({category}), "
                f"PM2.5: {cur.get('pm2_5')} µg/m³, PM10: {cur.get('pm10')} µg/m³, "
                f"NO2: {cur.get('nitrogen_dioxide')} µg/m³, O3: {cur.get('ozone')} µg/m³"
            )
            
            return SkillResult.ok(
                message="Air quality data retrieved.",
                data={
                    "resolved_location": resolved_name,
                    "summary": summary,
                    "aqi": aqi,
                    "category": category,
                    "pollutants": {
                        "pm2_5": cur.get("pm2_5"),
                        "pm10": cur.get("pm10"),
                        "carbon_monoxide": cur.get("carbon_monoxide"),
                        "nitrogen_dioxide": cur.get("nitrogen_dioxide"),
                        "sulphur_dioxide": cur.get("sulphur_dioxide"),
                        "ozone": cur.get("ozone")
                    }
                }
            )
        except Exception as e:
            return SkillResult.fail(f"Air quality fetch failed: {e}")
