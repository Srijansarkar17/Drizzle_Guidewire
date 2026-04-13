"""
MCP Client  —  single file
===========================
Calls all 3 MCP servers in parallel, sends signals to OpenAI
gpt-4o-mini for reasoning, estimates payout if claim triggered.

Run:
    uvicorn mcp_client:app --port 8000 --reload

Test:
    http://127.0.0.1:8000/assess?lat=13.0827&lon=80.2707&worker_id=DLV-001&zone=OMR-Chennai
"""

import os, asyncio, logging, json
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("mcp_client")

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────

OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "").strip()
openai_client = AsyncOpenAI(api_key=OPENAI_KEY)

if OPENAI_KEY:
    log.info(f"OpenAI key loaded: {OPENAI_KEY[:8]}...{OPENAI_KEY[-4:]} (len={len(OPENAI_KEY)})")
else:
    log.warning("OPENAI_API_KEY is empty — LLM reasoning will use formula fallback")

MCP_SERVERS = {
    "weather": "http://127.0.0.1:8001/score",
    "traffic": "http://127.0.0.1:8002/score",
    "social":  "http://127.0.0.1:8003/score",
}

# Base daily income per zone (INR) — based on known gig economy averages
# Source: NITI Aayog gig worker income report 2022
ZONE_BASE_INCOME = {
    "mumbai":    1400,
    "delhi":     1300,
    "bangalore": 1250,
    "hyderabad": 1100,
    "chennai":   1000,
    "noida":     1100,
    "pune":      1050,
    "kolkata":    950,
    "jaipur":     850,
    "default":   1000,
}


# ─────────────────────────────────────────────────────────────────
# SECTION 1 — COLLECT signals from all 3 MCP servers
# ─────────────────────────────────────────────────────────────────

async def fetch_server(name: str, url: str, params: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            log.info(f"{name} → level={data.get('risk_level')}")
            return {"status": "ok", "data": data}
    except Exception as e:
        log.error(f"{name} server failed: {e}")
        return {"status": "error", "server": name, "error": str(e)}


async def collect_signals(lat: float, lon: float,
                          worker_id: Optional[str],
                          zone: Optional[str]) -> dict:
    params = {"lat": lat, "lon": lon,
              "worker_id": worker_id, "zone": zone}
    weather, traffic, social = await asyncio.gather(
        fetch_server("weather", MCP_SERVERS["weather"], params),
        fetch_server("traffic", MCP_SERVERS["traffic"], params),
        fetch_server("social",  MCP_SERVERS["social"],  params),
    )
    return {"weather": weather, "traffic": traffic, "social": social}


# ─────────────────────────────────────────────────────────────────
# SECTION 2 — PAYOUT ESTIMATION (no random — formula based)
# ─────────────────────────────────────────────────────────────────

def get_base_income(zone: Optional[str]) -> int:
    if not zone:
        return ZONE_BASE_INCOME["default"]
    zone_lower = zone.lower()
    for city, income in ZONE_BASE_INCOME.items():
        if city in zone_lower:
            return income
    return ZONE_BASE_INCOME["default"]


def estimate_payout(zone: Optional[str],
                    weather_score: float,
                    traffic_score: float,
                    social_score: float,
                    confidence: str) -> dict:
    """
    Estimates payout from disruption scores — no randomness.
    Same inputs always produce same output.

    disruption_intensity = weighted average of 3 scores
    income_loss_ratio    = how much of the day was unworkable
    payout               = loss * 0.80  (80% coverage)
    """
    base_income = get_base_income(zone)

    disruption_intensity = (
        0.35 * weather_score +
        0.25 * traffic_score +
        0.25 * social_score
    )

    confidence_multiplier = {"HIGH": 1.0, "MEDIUM": 0.75, "LOW": 0.5}
    multiplier = confidence_multiplier.get(confidence, 0.75)

    income_loss_ratio = disruption_intensity * multiplier
    actual_income     = round(base_income * (1 - income_loss_ratio), 2)
    income_loss       = round(base_income - actual_income, 2)
    payout_amount     = round(income_loss * 0.80, 2)

    return {
        "base_daily_income_inr":   base_income,
        "estimated_actual_income": actual_income,
        "estimated_income_loss":   income_loss,
        "payout_amount_inr":       payout_amount,
        "coverage_percent":        80,
        "disruption_intensity":    round(disruption_intensity, 3),
    }


# ─────────────────────────────────────────────────────────────────
# SECTION 3 — REASON with OpenAI gpt-4o-mini
# ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are an AI insurance adjuster for a parametric insurance product
that protects gig delivery riders against income loss caused by
external disruptions like heavy rain, traffic jams, protests or bandhs.

You receive real-time signals from 3 sources:
  1. Weather server  — rain intensity, AQI, temperature, flood alerts
  2. Traffic server  — road congestion, closures, travel time delays
  3. Social server   — protests, bandhs, strikes, roadblocks from news and Reddit

Your job:
  - Reason over the 3 signals
  - Decide whether to trigger a claim
  - Identify the primary cause
  - Explain clearly in plain English

Decision rules:
  - HIGH on ANY single server → trigger claim
  - MEDIUM on 2 or more servers → trigger claim
  - MEDIUM on 1 server only → use judgment based on context
  - LOW across all 3 → no claim
  - If social server found real headlines → treat as strong evidence
  - Weather + social together is stronger than either alone

Respond in this exact JSON format with no extra text:
{
  "claim_triggered": true or false,
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "primary_cause": "weather" or "traffic" or "social" or "combined",
  "explanation": "2 to 4 sentences explaining your reasoning clearly",
  "recommended_action": "one line on what happens next for the rider"
}
"""


def build_user_message(worker_id: Optional[str],
                       zone: Optional[str],
                       signals: dict) -> str:

    def safe(signal: dict, *keys):
        try:
            d = signal["data"]
            for k in keys:
                d = d[k]
            return d
        except Exception:
            return "N/A"

    top_signals = []
    if signals["social"]["status"] == "ok":
        top_signals = (signals["social"]["data"]
                       .get("sub_scores", {})
                       .get("top_signals", []))

    headlines = "\n".join(
        f'    [{s["source"].upper()}] {s["title"]} '
        f'(keywords: {", ".join(s["keywords"])})'
        for s in top_signals[:3]
    ) or "    None found in last 3-6 hours"

    return f"""
Worker   : {worker_id or 'unknown'}
Zone     : {zone or 'unknown'}
Time UTC : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}

── WEATHER SIGNAL ──────────────────────────────
  Risk score : {safe(signals["weather"], "weather_risk_score")}
  Risk level : {safe(signals["weather"], "risk_level")}
  Condition  : {safe(signals["weather"], "sub_scores", "condition")}
  Rain mm/hr : {safe(signals["weather"], "sub_scores", "rain_mm_hr")}
  Temp C     : {safe(signals["weather"], "sub_scores", "temp_celsius")}
  AQI        : {safe(signals["weather"], "sub_scores", "aqi_raw")}
  Flood alert: {safe(signals["weather"], "sub_scores", "flood_alert")}

── TRAFFIC SIGNAL ──────────────────────────────
  Risk score    : {safe(signals["traffic"], "traffic_risk_score")}
  Risk level    : {safe(signals["traffic"], "risk_level")}
  Current speed : {safe(signals["traffic"], "sub_scores", "current_speed_kmph")} kmph
  Free flow     : {safe(signals["traffic"], "sub_scores", "free_flow_speed_kmph")} kmph
  Congestion    : {safe(signals["traffic"], "sub_scores", "congestion_score")}
  Road closed   : {safe(signals["traffic"], "sub_scores", "road_closed")}

── SOCIAL SIGNAL ───────────────────────────────
  Risk score  : {safe(signals["social"], "social_disruption_score")}
  Risk level  : {safe(signals["social"], "risk_level")}
  Reddit hits : {safe(signals["social"], "sub_scores", "reddit_hits")}
  News hits   : {safe(signals["social"], "sub_scores", "news_hits")}
  Headlines   :
{headlines}

Should an insurance claim be triggered for this rider?
"""


async def reason_with_llm(user_message: str) -> dict:
    if not OPENAI_KEY:
        log.warning("OPENAI_API_KEY not set — using formula fallback")
        return _formula_fallback(user_message)

    try:
        response = await openai_client.chat.completions.create(
            model    = "gpt-4o-mini",
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature     = 0.1,
            response_format = {"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        log.info(
            f"LLM → claim={result.get('claim_triggered')} "
            f"confidence={result.get('confidence')} "
            f"cause={result.get('primary_cause')}"
        )
        return {"status": "llm", "result": result}

    except Exception as e:
        log.error(f"OpenAI failed: {e} — using formula fallback")
        return _formula_fallback(user_message)


def _formula_fallback(user_message: str) -> dict:
    import re
    scores  = re.findall(r"Risk score\s+:\s+([\d.]+)", user_message)
    w = float(scores[0]) if len(scores) > 0 else 0.0
    t = float(scores[1]) if len(scores) > 1 else 0.0
    s = float(scores[2]) if len(scores) > 2 else 0.0

    final   = round(0.35 * w + 0.25 * t + 0.25 * s, 3)
    trigger = final >= 0.6 or w >= 0.6 or t >= 0.6 or s >= 0.6
    conf    = "HIGH" if final >= 0.6 else "MEDIUM" if final >= 0.3 else "LOW"

    if w >= t and w >= s:      cause = "weather"
    elif t >= w and t >= s:    cause = "traffic"
    else:                      cause = "social"

    return {
        "status": "fallback",
        "result": {
            "claim_triggered":    trigger,
            "confidence":         conf,
            "primary_cause":      cause,
            "explanation":        f"Formula fallback (LLM unavailable). Fused score={final}. Weather={w} Traffic={t} Social={s}.",
            "recommended_action": "Trigger claim review" if trigger else "No action needed.",
        }
    }


# ─────────────────────────────────────────────────────────────────
# SECTION 4 — FASTAPI APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(title="MCP Client — Gig Insurance Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class AssessRequest(BaseModel):
    lat:       float
    lon:       float
    worker_id: Optional[str] = None
    zone:      Optional[str] = None


@app.post("/assess")
@app.get("/assess")
async def assess(
    req:       AssessRequest = None,
    lat:       float         = Query(None),
    lon:       float         = Query(None),
    worker_id: Optional[str] = Query(None),
    zone:      Optional[str] = Query(None),
):
    if req:
        lat, lon, worker_id, zone = req.lat, req.lon, req.worker_id, req.zone
    if lat is None or lon is None:
        raise HTTPException(400, "lat and lon are required")

    log.info(f"── New assessment: worker={worker_id} zone={zone} ──")

    # Step 1 — collect all signals in parallel
    signals = await collect_signals(lat, lon, worker_id, zone)

    # Step 2 — reason with LLM
    user_message = build_user_message(worker_id, zone, signals)
    llm_response = await reason_with_llm(user_message)
    result       = llm_response["result"]

    # Step 3 — extract raw scores
    w_score = (signals["weather"]["data"].get("weather_risk_score", 0.0)
               if signals["weather"]["status"] == "ok" else 0.0)
    t_score = (signals["traffic"]["data"].get("traffic_risk_score", 0.0)
               if signals["traffic"]["status"] == "ok" else 0.0)
    s_score = (signals["social"]["data"].get("social_disruption_score", 0.0)
               if signals["social"]["status"] == "ok" else 0.0)

    # Step 4 — payout only if claim triggered
    payout = {}
    if result["claim_triggered"]:
        payout = estimate_payout(
            zone, w_score, t_score, s_score, result["confidence"]
        )

    return {
        "worker_id":        worker_id,
        "zone":             zone,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "reasoning_source": llm_response["status"],

        "claim_triggered":    result["claim_triggered"],
        "confidence":         result["confidence"],
        "primary_cause":      result["primary_cause"],
        "explanation":        result["explanation"],
        "recommended_action": result["recommended_action"],

        "payout": payout if payout else "No claim triggered",

        "signals": {
            "weather": {
                "score": w_score,
                "level": (signals["weather"]["data"].get("risk_level", "ERROR")
                          if signals["weather"]["status"] == "ok" else "ERROR"),
            },
            "traffic": {
                "score": t_score,
                "level": (signals["traffic"]["data"].get("risk_level", "ERROR")
                          if signals["traffic"]["status"] == "ok" else "ERROR"),
            },
            "social": {
                "score": s_score,
                "level": (signals["social"]["data"].get("risk_level", "ERROR")
                          if signals["social"]["status"] == "ok" else "ERROR"),
            },
        }
    }


@app.get("/health")
async def health():
    results = {}
    async with httpx.AsyncClient(timeout=5) as c:
        for name, url in MCP_SERVERS.items():
            try:
                r = await c.get(url.replace("/score", "/health"))
                results[name] = "ok" if r.status_code == 200 else "error"
            except Exception:
                results[name] = "unreachable"
    return {
        "status":            "ok",
        "openai_configured": bool(OPENAI_KEY),
        "mcp_servers":       results,
    }


@app.get("/")
async def root():
    return {
        "service": "MCP Client — Gig Insurance Agent",
        "endpoints": {
            "GET /assess": "Assess disruption risk + claim decision for a rider",
            "GET /health": "Check all 3 MCP servers and OpenAI key",
            "GET /docs":   "Swagger UI",
        },
        "example": "/assess?lat=13.0827&lon=80.2707&worker_id=DLV-001&zone=OMR-Chennai"
    }