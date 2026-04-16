"""
Traffic MCP Server  —  single file
====================================
Run:
    uvicorn traffic_server:app --port 8002 --reload

Test:
    http://127.0.0.1:8002/score?lat=28.5355&lon=77.3910&zone=Noida
"""

import os, logging
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
log = logging.getLogger("traffic_mcp")

TOMTOM_KEY = os.getenv("TOMTOM_API_KEY", "")


# ─────────────────────────────────────────────────────────────────
# SECTION 1 — FETCH  (TomTom Flow API)
# ─────────────────────────────────────────────────────────────────

async def fetch_traffic(lat: float, lon: float) -> dict:
    """
    TomTom Flow Segment API.
    Returns current speed vs free flow speed at given coordinates.
    Docs: https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
    """

    if not TOMTOM_KEY:
        log.warning("TOMTOM_API_KEY not configured — calling _mock_traffic")
        return _mock_traffic()

    url = (
        f"https://api.tomtom.com/traffic/services/4/flowSegmentData/"
        f"absolute/10/json"
    )
    params = {
        "point":   f"{lat},{lon}",
        "key":     TOMTOM_KEY,
        "unit":    "KMPH",
    }

    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            data = r.json()["flowSegmentData"]

        current_speed   = float(data["currentSpeed"])
        free_flow_speed = float(data["freeFlowSpeed"])
        current_tt      = int(data.get("currentTravelTime", 0))
        free_flow_tt    = int(data.get("freeFlowTravelTime", 0))
        road_closed     = bool(data.get("roadClosure", False))

        log.info(
            f"TomTom: current={current_speed}kmph "
            f"freeflow={free_flow_speed}kmph "
            f"closed={road_closed}"
        )

        return {
            "current_speed":    current_speed,
            "free_flow_speed":  free_flow_speed,
            "current_tt":       current_tt,
            "free_flow_tt":     free_flow_tt,
            "road_closed":      road_closed,
            "source":           "tomtom",
        }

    except httpx.HTTPStatusError as e:
        log.error(f"TomTom HTTP error: {e.response.status_code}")
        raise HTTPException(502, f"TomTom API returned error: {e.response.status_code}")
    except Exception as e:
        log.error(f"TomTom fetch failed: {e}")
        raise HTTPException(502, f"TomTom API failed: {str(e)}")


def _mock_traffic() -> dict:
    """
    Fallback mock when API key missing or call fails.
    Simulates moderate congestion so scoring logic can still be tested.
    """
    return {
        "current_speed":   20.0,
        "free_flow_speed": 50.0,
        "current_tt":      300,
        "free_flow_tt":    120,
        "road_closed":     False,
        "source":          "mock",
    }


# ─────────────────────────────────────────────────────────────────
# SECTION 2 — SCORE
# ─────────────────────────────────────────────────────────────────

def score_congestion(current_speed: float, free_flow_speed: float) -> float:
    """
    congestion_ratio = 1 - (current / freeflow)

    0.0  → traffic flowing freely
    0.3  → noticeable slowdown
    0.5  → moderate congestion
    0.7  → heavy congestion — riders significantly delayed
    1.0  → standstill / road closed
    """
    if free_flow_speed <= 0:
        return 0.0

    ratio = 1 - (current_speed / free_flow_speed)
    ratio = max(0.0, min(1.0, ratio))   # clamp to 0-1
    return round(ratio, 3)


def score_travel_time(current_tt: int, free_flow_tt: int) -> float:
    """
    Travel time delay ratio — secondary signal.
    If journey takes 3x longer than free flow → high score.
    """
    if free_flow_tt <= 0:
        return 0.0

    delay_ratio = (current_tt - free_flow_tt) / free_flow_tt
    delay_ratio = max(0.0, delay_ratio)

    if delay_ratio <= 0.0:   return 0.0
    if delay_ratio <= 0.5:   return round(delay_ratio * 0.4, 3)   # up to 0.2
    if delay_ratio <= 1.0:   return round(0.2 + (delay_ratio - 0.5) * 0.4, 3)
    if delay_ratio <= 2.0:   return round(0.4 + (delay_ratio - 1.0) * 0.3, 3)
    return 0.7


def fuse(congestion_score: float, tt_score: float, road_closed: bool) -> float:
    """
    Combine congestion + travel time delay + road closure.

    Weights:
      congestion  → 0.60  (primary signal)
      travel time → 0.30  (secondary)
      road closed → +0.30 fixed penalty on top
    """
    score = 0.60 * congestion_score + 0.30 * tt_score
    if road_closed:
        score += 0.30
    return round(min(1.0, score), 3)


def classify(score: float) -> str:
    if score < 0.30:  return "LOW"
    if score < 0.60:  return "MEDIUM"
    return "HIGH"


# ─────────────────────────────────────────────────────────────────
# SECTION 3 — FASTAPI APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Traffic MCP Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class TrafficRequest(BaseModel):
    lat:       float
    lon:       float
    worker_id: Optional[str] = None
    zone:      Optional[str] = None


@app.post("/score")
@app.get("/score")
async def score(
    req:       TrafficRequest = None,
    lat:       float          = Query(None),
    lon:       float          = Query(None),
    worker_id: Optional[str]  = Query(None),
    zone:      Optional[str]  = Query(None),
):
    if req:
        lat, lon, worker_id, zone = req.lat, req.lon, req.worker_id, req.zone
    if lat is None or lon is None:
        raise HTTPException(400, "lat and lon are required")

    # ── Fetch ─────────────────────────────────────────────────────
    traffic = await fetch_traffic(lat, lon)

    # ── Score ─────────────────────────────────────────────────────
    cong_s = score_congestion(
        traffic["current_speed"],
        traffic["free_flow_speed"]
    )
    tt_s   = score_travel_time(
        traffic["current_tt"],
        traffic["free_flow_tt"]
    )
    final  = fuse(cong_s, tt_s, traffic["road_closed"])
    level  = classify(final)

    log.info(
        f"[{worker_id or 'anon'}] zone={zone} "
        f"congestion={cong_s} tt={tt_s} closed={traffic['road_closed']} "
        f"→ {final} ({level})"
    )

    return {
        "worker_id":            worker_id,
        "zone":                 zone,
        "traffic_risk_score":   final,
        "risk_level":           level,
        "sub_scores": {
            "current_speed_kmph":   traffic["current_speed"],
            "free_flow_speed_kmph": traffic["free_flow_speed"],
            "congestion_score":     cong_s,
            "current_travel_time":  traffic["current_tt"],
            "free_flow_travel_time":traffic["free_flow_tt"],
            "travel_time_score":    tt_s,
            "road_closed":          traffic["road_closed"],
        },
        "source":    traffic["source"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tomtom_configured": bool(TOMTOM_KEY),
    }


@app.get("/mcp/tools")
async def mcp_tools():
    return {"tools": [{
        "name": "get_traffic_risk",
        "description": "Real-time traffic congestion risk for a delivery rider location.",
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
    if payload.get("name") != "get_traffic_risk":
        raise HTTPException(404, f"Unknown tool: {payload.get('name')}")
    args = payload.get("arguments", {})
    return await score(
        lat=args["lat"], lon=args["lon"],
        worker_id=args.get("worker_id"), zone=args.get("zone"),
    )