"""
Weather MCP Server  —  single file
===================================
Run:
    pip install fastapi uvicorn httpx python-dotenv
    uvicorn weather_server:app --port 8001 --reload

Test in browser:
    http://localhost:8001/score?lat=13.0827&lon=80.2707
"""

import os, asyncio, logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("weather_mcp")

# ─────────────────────────────────────────────────────────────────
# CONFIG  —  paste your keys in .env or directly here for testing
# ─────────────────────────────────────────────────────────────────

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "")   # weatherapi.com  — free, instant
OWM_KEY        = os.getenv("OWM_API_KEY",    "")   # openweathermap  — fallback


# ─────────────────────────────────────────────────────────────────
# SECTION 1 — FETCH  (WeatherAPI primary, OWM fallback, OpenAQ AQI)
# ─────────────────────────────────────────────────────────────────

async def fetch_weather(lat: float, lon: float) -> dict:
    """Try WeatherAPI first, fall back to OWM."""

    # ── WeatherAPI.com ────────────────────────────────────────────
    if WEATHERAPI_KEY:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.weatherapi.com/v1/current.json",
                    params={"key": WEATHERAPI_KEY, "q": f"{lat},{lon}", "aqi": "no"},
                )
                r.raise_for_status()
                d = r.json()["current"]
                log.info("Weather source: WeatherAPI.com")
                return {
                    "rain_mm":   float(d.get("precip_mm", 0)),
                    "temp_c":    float(d["temp_c"]),
                    "condition": d["condition"]["text"],
                    "code":      d["condition"]["code"],
                    "flood":     False,          # WeatherAPI has no alert feed
                    "source":    "weatherapi",
                }
        except Exception as e:
            log.warning(f"WeatherAPI failed: {e} — trying OWM")

    # ── OpenWeatherMap One Call 3.0 (fallback) ────────────────────
    if OWM_KEY:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.openweathermap.org/data/3.0/onecall",
                    params={"lat": lat, "lon": lon, "appid": OWM_KEY,
                            "units": "metric", "exclude": "minutely,daily,hourly"},
                )
                r.raise_for_status()
                data    = r.json()
                cur     = data["current"]
                alerts  = data.get("alerts", [])
                flood_kw = {"flood", "cyclone", "storm", "heavy rain", "red alert"}
                flood   = any(
                    any(kw in a.get("event", "").lower() for kw in flood_kw)
                    for a in alerts
                )
                log.info("Weather source: OWM One Call 3.0")
                return {
                    "rain_mm":   float(cur.get("rain", {}).get("1h", 0)),
                    "temp_c":    float(cur["temp"]),
                    "condition": cur["weather"][0]["description"].title(),
                    "code":      cur["weather"][0]["id"],
                    "flood":     flood,
                    "source":    "owm",
                }
    log.warning("No weather API available — generating mock weather data")
    # Simulate heavy rain logic based on coordinates for testing
    sim_rain = 35.0 if lat > 20 else 5.0
    sim_temp = 38.0 if lon > 70 else 25.0
    return {
        "rain_mm":   sim_rain,
        "temp_c":    sim_temp,
        "condition": "Heavy Rain" if sim_rain > 20 else "Moderate Rain",
        "code":      502 if sim_rain > 20 else 500,
        "flood":     sim_rain > 30,
        "source":    "mock",
    }


async def fetch_aqi(lat: float, lon: float) -> float:
    """
    OpenAQ v3 — no API key needed.
    Returns US AQI float. Falls back to OWM Air Pollution if OpenAQ finds nothing.
    """

    # ── OpenAQ v3 ─────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            # Find nearest sensor
            r = await c.get(
                "https://api.openaq.org/v3/locations",
                params={"coordinates": f"{lat},{lon}", "radius": 25000,
                        "limit": 5, "order_by": "distance", "parameter": "pm25"},
            )
            r.raise_for_status()
            locs = r.json().get("results", [])

            if locs:
                loc_id = locs[0]["id"]
                sr = await c.get(f"https://api.openaq.org/v3/locations/{loc_id}/latest")
                sr.raise_for_status()
                for s in sr.json().get("results", []):
                    if s.get("parameter", {}).get("name") == "pm25":
                        pm25 = float(s["value"])
                        log.info(f"AQI source: OpenAQ  pm2.5={pm25}")
                        return _pm25_to_aqi(pm25)
    except Exception as e:
        log.warning(f"OpenAQ failed: {e} — trying OWM AQI")

    # ── OWM Air Pollution fallback ────────────────────────────────
    if OWM_KEY:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.openweathermap.org/data/2.5/air_pollution",
                    params={"lat": lat, "lon": lon, "appid": OWM_KEY},
                )
                r.raise_for_status()
                pm25 = float(r.json()["list"][0]["components"].get("pm2_5", 0))
                log.info(f"AQI source: OWM Air Pollution  pm2.5={pm25}")
                return _pm25_to_aqi(pm25)
        except Exception as e:
            log.warning(f"OWM AQI failed: {e}")

    log.warning("No AQI source available — defaulting to 50")
    return 50.0   # assume moderate


def _pm25_to_aqi(pm25: float) -> float:
    """EPA standard PM2.5 → US AQI conversion."""
    breakpoints = [
        (0.0,   12.0,   0,  50),
        (12.1,  35.4,  51, 100),
        (35.5,  55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 500.4, 301, 500),
    ]
    for lo, hi, i_lo, i_hi in breakpoints:
        if lo <= pm25 <= hi:
            return round(((i_hi - i_lo) / (hi - lo)) * (pm25 - lo) + i_lo, 1)
    return 500.0


# ─────────────────────────────────────────────────────────────────
# SECTION 2 — SCORE  (normalise each signal → fuse → classify)
# ─────────────────────────────────────────────────────────────────

def score_rain(mm: float, code: int = 0) -> float:
    """
    IMD intensity bands → 0-1.
    Falls back to OWM condition code if mm == 0.
    """
    if mm <= 0:
        # OWM heavy rain codes as fallback
        heavy_codes = {502, 503, 504, 511, 522, 531}
        if code in heavy_codes:   return 0.85
        if 500 <= code <= 531:    return 0.30
        return 0.0

    bands = [(7, 0.25), (15, 0.50), (30, 0.80), (50, 0.95)]
    prev_mm, prev_s = 0, 0.0
    for upper_mm, upper_s in bands:
        if mm <= upper_mm:
            ratio = (mm - prev_mm) / (upper_mm - prev_mm)
            return round(prev_s + ratio * (upper_s - prev_s), 3)
        prev_mm, prev_s = upper_mm, upper_s
    return 1.0   # >= 50 mm/hr


def score_aqi(aqi: float) -> float:
    """US AQI → 0-1."""
    bands = [(50, 0.0), (100, 0.20), (150, 0.40), (200, 0.60), (300, 0.85)]
    prev_aqi, prev_s = 0, 0.0
    for upper_aqi, upper_s in bands:
        if aqi <= upper_aqi:
            if upper_aqi == 50:   return 0.0
            ratio = (aqi - prev_aqi) / (upper_aqi - prev_aqi)
            return round(prev_s + ratio * (upper_s - prev_s), 3)
        prev_aqi, prev_s = upper_aqi, upper_s
    return 1.0   # >= 300


def score_temp(temp_c: float, flood: bool) -> float:
    """Heat extremes + flood alert → 0-1."""
    s = 0.0
    if   temp_c >= 42:  s += 0.60
    elif temp_c >= 38:  s += 0.35
    elif temp_c >= 35:  s += 0.15
    elif temp_c <=  5:  s += 0.40
    if flood:           s += 0.30
    return min(1.0, round(s, 3))


def fuse(rain_s: float, aqi_s: float, temp_s: float) -> float:
    return round(0.50 * rain_s + 0.30 * aqi_s + 0.20 * temp_s, 3)


def classify(score: float) -> str:
    if score < 0.30:  return "LOW"
    if score < 0.60:  return "MEDIUM"
    return "HIGH"


# ─────────────────────────────────────────────────────────────────
# SECTION 3 — FASTAPI APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Weather MCP Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class WeatherRequest(BaseModel):
    lat:       float
    lon:       float
    worker_id: Optional[str] = None
    zone:      Optional[str] = None


@app.post("/score")
@app.get("/score")
async def score(
    req:       WeatherRequest = None,
    lat:       float          = Query(None),
    lon:       float          = Query(None),
    worker_id: Optional[str]  = Query(None),
    zone:      Optional[str]  = Query(None),
):
    # Accept both POST body and GET query params
    if req:
        lat, lon, worker_id, zone = req.lat, req.lon, req.worker_id, req.zone
    if lat is None or lon is None:
        raise HTTPException(400, "lat and lon are required")

    # ── Fetch concurrently ────────────────────────────────────────
    weather, aqi_raw = await asyncio.gather(
        fetch_weather(lat, lon),
        fetch_aqi(lat, lon),
    )

    # ── Score ─────────────────────────────────────────────────────
    rain_s = score_rain(weather["rain_mm"], weather.get("code", 0))
    aqi_s  = score_aqi(aqi_raw)
    temp_s = score_temp(weather["temp_c"], weather["flood"])
    final  = fuse(rain_s, aqi_s, temp_s)
    level  = classify(final)

    log.info(f"[{worker_id or 'anon'}] rain={weather['rain_mm']}mm "
             f"aqi={aqi_raw} temp={weather['temp_c']}°C "
             f"→ {final} ({level})")

    return {
        "worker_id":          worker_id,
        "zone":               zone,
        "weather_risk_score": final,
        "risk_level":         level,
        "sub_scores": {
            "rain_mm_hr":     weather["rain_mm"],
            "rain_score":     rain_s,
            "aqi_raw":        aqi_raw,
            "aqi_score":      aqi_s,
            "temp_celsius":   weather["temp_c"],
            "temp_score":     temp_s,
            "flood_alert":    weather["flood"],
            "condition":      weather["condition"],
        },
        "source":    weather["source"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "apis_configured": {
            "weatherapi": bool(WEATHERAPI_KEY),
            "owm":        bool(OWM_KEY),
            "openaq":     True,
        }
    }


# ── MCP tool endpoints (for LLM orchestrators) ────────────────────

@app.get("/mcp/tools")
async def mcp_tools():
    return {"tools": [{
        "name": "get_weather_risk",
        "description": "Real-time weather disruption risk for a delivery rider location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat":       {"type": "number"},
                "lon":       {"type": "number"},
                "worker_id": {"type": "string"},
                "zone":      {"type": "string"},
            },
            "required": ["lat", "lon"],
        },
    }]}


@app.post("/mcp/call")
async def mcp_call(payload: dict):
    if payload.get("name") != "get_weather_risk":
        raise HTTPException(404, f"Unknown tool: {payload.get('name')}")
    args = payload.get("arguments", {})
    result = await score(
        lat=args["lat"], lon=args["lon"],
        worker_id=args.get("worker_id"), zone=args.get("zone"),
    )
    return {"content": [{"type": "json", "json": result}]}