import os
import logging
from pathlib import Path
from typing import Optional
import httpx
import urllib.parse

from . import scraper

# ── Module-level HTTP client (reuses connection pool) ─────────────────────────
_weather_client: httpx.AsyncClient | None = None

def _get_weather_client() -> httpx.AsyncClient:
    global _weather_client
    if _weather_client is None:
        _weather_client = httpx.AsyncClient(timeout=8.0)
    return _weather_client


async def close_http_clients() -> None:
    global _weather_client
    if _weather_client is not None:
        await _weather_client.aclose()
        _weather_client = None
    await scraper.close_client()


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONV_DIR = DATA_DIR / "conversations"

# Common city aliases / alternate spellings (especially Indian cities)
CITY_ALIASES: dict[str, str] = {
    "banglore": "Bengaluru", "bangalore": "Bengaluru", "bengalore": "Bengaluru",
    "banglure": "Bengaluru", "bangluru": "Bengaluru", "bengaluru": "Bengaluru",
    "bombay": "Mumbai", "bombai": "Mumbai",
    "madras": "Chennai", "madrass": "Chennai",
    "calcutta": "Kolkata", "kolkatta": "Kolkata", "calicut": "Kozhikode",
    "poona": "Pune", "cochin": "Kochi", "kochin": "Kochi",
    "trivandrum": "Thiruvananthapuram", "trissur": "Thrissur", "trichur": "Thrissur",
    "mysore": "Mysuru", "mangalore": "Mangaluru", "hubli": "Hubballi",
    "vizag": "Visakhapatnam", "baroda": "Vadodara",
    "new delhi": "New Delhi", "delhi": "New Delhi",
    "hydrabad": "Hyderabad",
}


def get_profile_location() -> Optional[str]:
    import json
    try:
        p_path = DATA_DIR / "profile.txt"
        if p_path.exists():
            data = json.loads(p_path.read_text(encoding="utf-8"))
            return data.get("user_profile", {}).get("location")
    except Exception:
        pass
    return None


_geo_logger = logging.getLogger("Geocoder")


async def geocode_location(location: str) -> Optional[tuple[float, float, str]]:
    """Geocodes a location name using Open-Meteo's geocoding API.
    Returns (lat, lon, resolved_name) or None.
    Applies CITY_ALIASES normalization for common misspellings.
    """
    if not location or not location.strip():
        return None

    # Normalize via alias map
    normalized = CITY_ALIASES.get(location.strip().lower(), location.strip())
    if normalized != location.strip():
        _geo_logger.info(f"[Geocoder] Alias resolved: '{location}' → '{normalized}'")

    try:
        encoded_loc = urllib.parse.quote(normalized)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_loc}&count=1&language=en&format=json"
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(geo_url)
        if r.status_code == 200:
            data = r.json()
            if data.get("results"):
                res = data["results"][0]
                lat = float(res["latitude"])
                lon = float(res["longitude"])
                resolved_name = res.get("name", normalized)
                if res.get("admin1"):
                    resolved_name += f", {res.get('admin1')}"
                if res.get("country"):
                    resolved_name += f", {res.get('country')}"
                return lat, lon, resolved_name
            else:
                _geo_logger.warning(f"[Geocoder] No results for '{normalized}' (original: '{location}')")
        else:
            _geo_logger.warning(f"[Geocoder] Geocoding API returned HTTP {r.status_code} for '{normalized}'")
    except Exception as exc:
        _geo_logger.warning(f"[Geocoder] Exception geocoding '{normalized}': {exc}")
    return None


async def get_weather(lat: Optional[float] = None, lon: Optional[float] = None, location: Optional[str] = None) -> dict:
    resolved_name = None
    if location and location.strip().upper() != "DEFAULT":
        res = await geocode_location(location)
        if res:
            lat, lon, resolved_name = res
    
    if lat is None: lat = float(os.getenv("FRIDAY_LAT", 28.6))
    if lon is None: lon = float(os.getenv("FRIDAY_LON", 77.2))

    # If using default coordinates, try fallback to user's profile location
    if lat == 28.6 and lon == 77.2 and not resolved_name:
        ploc = get_profile_location()
        if ploc:
            res = await geocode_location(ploc)
            if res:
                lat, lon, resolved_name = res

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m,relativehumidity_2m"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&timezone=auto&forecast_days=1"
        )
        r = await _get_weather_client().get(url)
        r.raise_for_status()
        d = r.json()
        cur = d["current"]
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
        cond = WMO.get(cur["weathercode"], "Unknown")
        hi, lo = d["daily"]["temperature_2m_max"][0], d["daily"]["temperature_2m_min"][0]
        loc_prefix = f"{resolved_name}: " if resolved_name else ""
        summary = f"{loc_prefix}{cond}, {cur['temperature_2m']}°C (High {hi} / Low {lo}), Humidity {cur['relativehumidity_2m']}%, Wind {cur['windspeed_10m']} km/h"
        return {"temp_c": cur["temperature_2m"], "condition": cond,
                "humidity": cur["relativehumidity_2m"], "wind_kph": cur["windspeed_10m"],
                "max_c": hi, "min_c": lo, "summary": summary, "resolved_location": resolved_name}
    except Exception as e:
        return {"error": str(e)}
