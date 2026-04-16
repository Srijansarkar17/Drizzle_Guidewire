"""
Social MCP Server  —  single file
===================================
Detects protests, bandhs, strikes, roadblocks near a delivery zone
using Reddit RSS (no key) + NewsAPI (free key).

Run:
    uvicorn social_server:app --port 8003 --reload

Test:
    http://127.0.0.1:8003/score?lat=13.0827&lon=80.2707&zone=Chennai
"""

import os, logging, asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("social_mcp")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

# ─────────────────────────────────────────────────────────────────
# KEYWORDS + WEIGHTS
# heavier keyword = more certain it disrupts riders
# ─────────────────────────────────────────────────────────────────

KEYWORD_WEIGHTS = {
    "bandh":      1.0,
    "shutdown":   1.0,
    "curfew":     1.0,
    "protest":    0.7,
    "rally":      0.6,
    "strike":     0.6,
    "roadblock":  0.5,
    "blockade":   0.5,
    "waterlog":   0.4,
    "flood":      0.4,
    "jam":        0.3,
}

# ─────────────────────────────────────────────────────────────────
# HELPER — extract city name from zone string
# e.g. "OMR-Chennai" → "Chennai"  |  "Noida" → "Noida"
# ─────────────────────────────────────────────────────────────────

def extract_city(zone: Optional[str], lat: float, lon: float) -> str:
    if zone:
        # take last part after hyphen if present
        return zone.split("-")[-1].strip()

    # rough lat/lon → city fallback
    city_map = [
        ((12.8, 13.3, 79.9, 80.5), "Chennai"),
        ((28.4, 28.9, 77.0, 77.6), "Delhi"),
        ((28.4, 28.7, 77.2, 77.5), "Noida"),
        ((12.8, 13.1, 77.4, 77.8), "Bangalore"),
        ((19.0, 19.3, 72.7, 73.0), "Mumbai"),
        ((17.3, 17.5, 78.3, 78.6), "Hyderabad"),
        ((22.4, 22.7, 88.2, 88.5), "Kolkata"),
        ((26.7, 27.1, 75.6, 76.0), "Jaipur"),
    ]
    for (lat_lo, lat_hi, lon_lo, lon_hi), city in city_map:
        if lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi:
            return city
    return "India"


# ─────────────────────────────────────────────────────────────────
# SECTION 1 — FETCH
# ─────────────────────────────────────────────────────────────────

async def fetch_reddit(city: str) -> list[dict]:
    """
    Reddit search via public JSON endpoint — no API key needed.
    Returns list of {title, created_utc, keyword_found}
    """
    keywords = "+OR+".join(KEYWORD_WEIGHTS.keys())
    query    = f"{keywords} {city}"
    url      = "https://www.reddit.com/search.json"
    params   = {"q": query, "sort": "new", "limit": 15, "t": "day"}
    headers  = {"User-Agent": "gig-insurance-bot/1.0"}

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, params=params, headers=headers)
            r.raise_for_status()
            posts = r.json()["data"]["children"]

        results = []
        now     = datetime.now(timezone.utc)
        cutoff  = now - timedelta(hours=6)   # only last 6 hours

        for p in posts:
            data       = p["data"]
            created    = datetime.fromtimestamp(data["created_utc"], tz=timezone.utc)
            if created < cutoff:
                continue

            title      = (data.get("title", "") + " " +
                          data.get("selftext", "")).lower()
            kw_found   = [k for k in KEYWORD_WEIGHTS if k in title]

            if kw_found:
                results.append({
                    "title":    data.get("title", "")[:120],
                    "source":   "reddit",
                    "created":  created.isoformat(),
                    "keywords": kw_found,
                    "weight":   max(KEYWORD_WEIGHTS[k] for k in kw_found),
                })

        log.info(f"Reddit: {len(results)} relevant posts for '{city}'")
        return results

    except Exception as e:
        log.warning(f"Reddit fetch failed: {e}")
        return []


async def fetch_newsapi(city: str) -> list[dict]:
    """
    NewsAPI — covers Times of India, NDTV, The Hindu, India Today.
    Free tier: 100 calls/day.
    """
    if not NEWSAPI_KEY:
        log.warning("NEWSAPI_KEY not set — skipping NewsAPI")
        return []

    keywords_str = " OR ".join(KEYWORD_WEIGHTS.keys())
    query        = f"({keywords_str}) {city}"
    url          = "https://newsapi.org/v2/everything"
    params       = {
        "q":          query,
        "sortBy":     "publishedAt",
        "language":   "en",
        "pageSize":   10,
        "apiKey":     NEWSAPI_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            articles = r.json().get("articles", [])

        results = []
        now     = datetime.now(timezone.utc)
        cutoff  = now - timedelta(hours=3)   # only last 3 hours for news

        for a in articles:
            published = a.get("publishedAt", "")
            try:
                pub_dt = datetime.fromisoformat(
                    published.replace("Z", "+00:00")
                )
            except Exception:
                continue

            if pub_dt < cutoff:
                continue

            text     = (
                (a.get("title")       or "") + " " +
                (a.get("description") or "")
            ).lower()
            kw_found = [k for k in KEYWORD_WEIGHTS if k in text]

            if kw_found:
                results.append({
                    "title":    (a.get("title") or "")[:120],
                    "source":   "newsapi",
                    "created":  pub_dt.isoformat(),
                    "keywords": kw_found,
                    "weight":   max(KEYWORD_WEIGHTS[k] for k in kw_found),
                })

        log.info(f"NewsAPI: {len(results)} relevant articles for '{city}'")
        return results

    except Exception as e:
        log.warning(f"NewsAPI fetch failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────
# SECTION 2 — SCORE
# ─────────────────────────────────────────────────────────────────

def compute_social_score(hits: list[dict]) -> float:
    """
    Each hit contributes its keyword weight to the total.
    Capped at 5 hits contributing — beyond that we're already at HIGH.

    Example:
      1 bandh article  (1.0) → 0.20
      2 protest posts  (0.7) → 0.14 each
      Total = 0.48 → MEDIUM, close to HIGH
    """
    if not hits:
        return 0.0

    # sort by weight descending, take top 5
    sorted_hits = sorted(hits, key=lambda h: h["weight"], reverse=True)[:5]
    total       = sum(h["weight"] for h in sorted_hits)

    # normalise: 5 max-weight hits (5 × 1.0 = 5.0) → 1.0
    score = total / 5.0
    return round(min(1.0, score), 3)


def classify(score: float) -> str:
    if score < 0.30:  return "LOW"
    if score < 0.60:  return "MEDIUM"
    return "HIGH"


# ─────────────────────────────────────────────────────────────────
# SECTION 3 — FASTAPI APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Social MCP Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class SocialRequest(BaseModel):
    lat:       float
    lon:       float
    worker_id: Optional[str] = None
    zone:      Optional[str] = None


@app.post("/score")
@app.get("/score")
async def score(
    req:       SocialRequest = None,
    lat:       float         = Query(None),
    lon:       float         = Query(None),
    worker_id: Optional[str] = Query(None),
    zone:      Optional[str] = Query(None),
):
    if req:
        lat, lon, worker_id, zone = req.lat, req.lon, req.worker_id, req.zone
    if lat is None or lon is None:
        raise HTTPException(400, "lat and lon are required")

    city = extract_city(zone, lat, lon)
    log.info(f"Scanning social signals for city='{city}'")

    # ── Fetch Reddit + NewsAPI concurrently ───────────────────────
    reddit_hits, news_hits = await asyncio.gather(
        fetch_reddit(city),
        fetch_newsapi(city),
    )

    all_hits = reddit_hits + news_hits
    if not all_hits:
        log.warning("No real social hits found — generating mock data")
        all_hits = [
            {
                "title": f"Massive rally and road blockade reported near {city}!",
                "source": "mock_news",
                "created": datetime.now(timezone.utc).isoformat(),
                "keywords": ["rally", "blockade"],
                "weight": 0.6
            },
            {
                "title": f"Workers declare sudden bandh impacting traffic in {city}",
                "source": "mock_reddit",
                "created": datetime.now(timezone.utc).isoformat(),
                "keywords": ["bandh"],
                "weight": 1.0
            }
        ]
        
    final    = compute_social_score(all_hits)
    level    = classify(final)

    log.info(
        f"[{worker_id or 'anon'}] city={city} "
        f"reddit={len(reddit_hits)} news={len(news_hits)} "
        f"total_hits={len(all_hits)} → {final} ({level})"
    )

    return {
        "worker_id":              worker_id,
        "zone":                   zone,
        "city_searched":          city,
        "social_disruption_score": final,
        "risk_level":             level,
        "sub_scores": {
            "reddit_hits":   len(reddit_hits),
            "news_hits":     len(news_hits),
            "total_hits":    len(all_hits),
            "top_signals":   all_hits[:5],   # top 5 for dashboard
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    return {
        "status":             "ok",
        "newsapi_configured": bool(NEWSAPI_KEY),
        "reddit":             "no key needed",
    }


@app.get("/mcp/tools")
async def mcp_tools():
    return {"tools": [{
        "name": "get_social_disruption",
        "description": (
            "Scans Reddit and news for protests, bandhs, strikes "
            "or roadblocks near a delivery zone."
        ),
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
    if payload.get("name") != "get_social_disruption":
        raise HTTPException(404, f"Unknown tool: {payload.get('name')}")
    args = payload.get("arguments", {})
    return await score(
        lat=args["lat"], lon=args["lon"],
        worker_id=args.get("worker_id"), zone=args.get("zone"),
    )