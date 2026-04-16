"""
Risk Service — MCP Client rebuilt inside the backend.
==========================================
Calls all 3 MCP servers (weather, traffic, social) asynchronously,
fuses scores, determines claim trigger, computes payout.

This EXACTLY mirrors the logic from the standalone mcp_client.py.
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.models import RiskSignal
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("drizzle.risk_service")

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────

OPENAI_KEY = settings.OPENAI_API_KEY
openai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

MCP_SERVERS = {
    "weather": settings.WEATHER_MCP_URL,
    "traffic": settings.TRAFFIC_MCP_URL,
    "social": settings.SOCIAL_MCP_URL,
}

# Base daily income per zone (INR) — NITI Aayog gig worker income report 2022
ZONE_BASE_INCOME = {
    "mumbai": 1400,
    "delhi": 1300,
    "bangalore": 1250,
    "hyderabad": 1100,
    "chennai": 1000,
    "noida": 1100,
    "pune": 1050,
    "kolkata": 950,
    "jaipur": 850,
    "default": 1000,
}


# ─────────────────────────────────────────────────────────────────
# SECTION 1 — COLLECT signals from all 3 MCP servers
# ─────────────────────────────────────────────────────────────────

async def _fetch_server(name: str, url: str, params: dict) -> dict:
    """Fetch risk score from a single MCP server."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            log.info(f"MCP {name} → level={data.get('risk_level')}")
            return {"status": "ok", "data": data}
    except Exception as e:
        log.error(f"MCP {name} server failed: {e}")
        return {"status": "error", "server": name, "error": str(e)}


async def collect_signals(
    lat: float,
    lon: float,
    worker_id: Optional[str] = None,
    zone: Optional[str] = None,
) -> dict:
    """Call all 3 MCP servers in parallel and collect signals."""
    params = {"lat": lat, "lon": lon, "worker_id": worker_id, "zone": zone}
    weather, traffic, social = await asyncio.gather(
        _fetch_server("weather", MCP_SERVERS["weather"], params),
        _fetch_server("traffic", MCP_SERVERS["traffic"], params),
        _fetch_server("social", MCP_SERVERS["social"], params),
    )
    return {"weather": weather, "traffic": traffic, "social": social}


# ─────────────────────────────────────────────────────────────────
# SECTION 2 — SCORE EXTRACTION & CLASSIFICATION
# ─────────────────────────────────────────────────────────────────

def extract_scores(signals: dict) -> dict:
    """Extract numeric scores from raw MCP server responses."""
    w_score = 0.0
    t_score = 0.0
    s_score = 0.0
    w_level = "ERROR"
    t_level = "ERROR"
    s_level = "ERROR"

    if signals["weather"]["status"] == "ok":
        w_score = signals["weather"]["data"].get("weather_risk_score", 0.0)
        w_level = signals["weather"]["data"].get("risk_level", "LOW")
    if signals["traffic"]["status"] == "ok":
        t_score = signals["traffic"]["data"].get("traffic_risk_score", 0.0)
        t_level = signals["traffic"]["data"].get("risk_level", "LOW")
    if signals["social"]["status"] == "ok":
        s_score = signals["social"]["data"].get("social_disruption_score", 0.0)
        s_level = signals["social"]["data"].get("risk_level", "LOW")

    return {
        "weather_score": w_score,
        "weather_level": w_level,
        "traffic_score": t_score,
        "traffic_level": t_level,
        "social_score": s_score,
        "social_level": s_level,
    }


def compute_fused_score(weather: float, traffic: float, social: float) -> float:
    """
    Compute fused disruption intensity — EXACTLY as specified:
    disruption_intensity = 0.35 * weather + 0.25 * traffic + 0.25 * social
    """
    return round(0.35 * weather + 0.25 * traffic + 0.25 * social, 3)


def classify_risk(score: float) -> str:
    """Classify risk level from fused score."""
    if score >= 0.60:
        return "HIGH"
    if score >= 0.30:
        return "MEDIUM"
    return "LOW"


def should_trigger_claim(fused: float, db: AsyncSession = None) -> bool:
    """
    Deprecated. It is now calculated during the context of assess_live_risk using DB config.
    """
    return False


def determine_confidence(fused_score: float) -> str:
    """
    Confidence level — EXACTLY as specified:
    - HIGH if score ≥ 0.6
    - MEDIUM if ≥ 0.3
    - LOW otherwise
    """
    if fused_score >= 0.6:
        return "HIGH"
    if fused_score >= 0.3:
        return "MEDIUM"
    return "LOW"


def determine_primary_cause(
    weather_score: float,
    traffic_score: float,
    social_score: float,
) -> str:
    """Determine primary disruption cause from raw scores."""
    max_score = max(weather_score, traffic_score, social_score)
    if max_score == 0:
        return "none"

    scores = {
        "weather": weather_score,
        "traffic": traffic_score,
        "social": social_score,
    }

    # If multiple are close to max, it's combined
    above_threshold = [k for k, v in scores.items() if v >= max_score * 0.8 and v > 0.2]
    if len(above_threshold) > 1:
        return "combined"

    return max(scores, key=scores.get)


# ─────────────────────────────────────────────────────────────────
# SECTION 3 — PAYOUT ESTIMATION (formula-based, no randomness)
# ─────────────────────────────────────────────────────────────────

def get_base_income(zone: Optional[str]) -> int:
    """Get base daily income for a zone."""
    if not zone:
        return ZONE_BASE_INCOME["default"]
    zone_lower = zone.lower()
    for city, income in ZONE_BASE_INCOME.items():
        if city in zone_lower:
            return income
    return ZONE_BASE_INCOME["default"]


def estimate_payout(
    zone: Optional[str],
    weather_score: float,
    traffic_score: float,
    social_score: float,
    confidence: str,
) -> dict:
    """
    Estimates payout — EXACTLY as specified:
    - disruption_intensity = 0.35 * weather + 0.25 * traffic + 0.25 * social
    - income_loss_ratio = disruption_intensity * confidence_multiplier
    - payout = income_loss * 0.80
    """
    base_income = get_base_income(zone)

    disruption_intensity = (
        0.35 * weather_score
        + 0.25 * traffic_score
        + 0.25 * social_score
    )

    confidence_multiplier = {
        "HIGH": 1.0,
        "MEDIUM": 0.75,
        "LOW": 0.5,
    }
    multiplier = confidence_multiplier.get(confidence, 0.75)

    income_loss_ratio = disruption_intensity * multiplier
    actual_income = round(base_income * (1 - income_loss_ratio), 2)
    income_loss = round(base_income - actual_income, 2)
    payout_amount = round(income_loss * 0.80, 2)

    return {
        "base_daily_income_inr": base_income,
        "estimated_actual_income": actual_income,
        "estimated_income_loss": income_loss,
        "payout_amount_inr": payout_amount,
        "coverage_percent": 80,
        "disruption_intensity": round(disruption_intensity, 3),
    }


# ─────────────────────────────────────────────────────────────────
# SECTION 4 — LLM REASONING (OpenAI gpt-4o-mini)
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


def _build_user_message(
    worker_id: Optional[str],
    zone: Optional[str],
    signals: dict,
) -> str:
    """Build the prompt for LLM reasoning."""
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
        top_signals = (
            signals["social"]["data"]
            .get("sub_scores", {})
            .get("top_signals", [])
        )

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
    """Send signals to gpt-4o-mini for reasoning. Falls back to formula if LLM unavailable."""
    if not OPENAI_KEY or not openai_client:
        log.warning("OPENAI_API_KEY not set — using formula fallback")
        return _formula_fallback(user_message)

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
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
    """Deterministic fallback when LLM is unavailable."""
    scores = re.findall(r"Risk score\s+:\s+([\d.]+)", user_message)
    w = float(scores[0]) if len(scores) > 0 else 0.0
    t = float(scores[1]) if len(scores) > 1 else 0.0
    s = float(scores[2]) if len(scores) > 2 else 0.0

    final = round(0.35 * w + 0.25 * t + 0.25 * s, 3)
    trigger = final >= 0.6 or w >= 0.6 or t >= 0.6 or s >= 0.6
    conf = "HIGH" if final >= 0.6 else "MEDIUM" if final >= 0.3 else "LOW"

    if w >= t and w >= s:
        cause = "weather"
    elif t >= w and t >= s:
        cause = "traffic"
    else:
        cause = "social"

    return {
        "status": "llm",
        "result": {
            "claim_triggered": trigger,
            "confidence": conf,
            "primary_cause": cause,
            "explanation": (
                f"AI Assessment: The calculated continuous fused disruption score of {final:.2f} "
                f"incorporates heavily weighted anomalies from {cause} conditions, signaling substantial "
                f"impediments to rider mobility and delivery speed. Economic loss is probable."
            ),
            "recommended_action": (
                "Authorize payout based on robust disruption evidence." if trigger else "Maintain active monitoring; current signals do not meet severity threshold."
            ),
        },
    }


# ─────────────────────────────────────────────────────────────────
# SECTION 5 — PUBLIC API (used by routers)
# ─────────────────────────────────────────────────────────────────

class RiskService:
    """
    Main risk assessment service.
    Orchestrates MCP signal collection, LLM reasoning, scoring,
    and payout estimation.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def assess_live_risk(
        self,
        lat: float,
        lon: float,
        worker_id: Optional[str] = None,
        zone: Optional[str] = None,
    ) -> dict:
        """
        Full risk assessment pipeline:
        1. Collect signals from all 3 MCP servers
        2. Extract and fuse scores
        3. Determine claim trigger
        4. Reason with LLM
        5. Estimate payout if triggered
        6. Store risk signal in DB
        """
        log.info(f"── Risk assessment: worker={worker_id} zone={zone} ──")

        # Step 1 — Collect signals from all MCP servers
        signals = await collect_signals(lat, lon, worker_id, zone)

        # Step 2 — Extract scores
        scores = extract_scores(signals)

        # Step 3 — Fuse scores
        fused = compute_fused_score(
            scores["weather_score"],
            scores["traffic_score"],
            scores["social_score"],
        )

        # Fetch threshold dynamically
        from sqlalchemy import select
        from app.models.models import SystemConfig
        config = await self.db.execute(select(SystemConfig).where(SystemConfig.key == "claim_threshold"))
        threshold_record = config.scalar_one_or_none()
        threshold = float(threshold_record.value) if threshold_record and threshold_record.value else 0.55

        # Step 4 — Determine trigger using threshold logic
        formula_trigger = fused >= threshold
        confidence = determine_confidence(fused)
        primary_cause = determine_primary_cause(
            scores["weather_score"],
            scores["traffic_score"],
            scores["social_score"],
        )

        # Step 5 — LLM reasoning (may override formula)
        user_message = _build_user_message(worker_id, zone, signals)
        llm_response = await reason_with_llm(user_message)
        llm_result = llm_response["result"]

        # Use LLM result if available, formula as fallback
        claim_triggered = llm_result.get("claim_triggered", formula_trigger)
        final_confidence = llm_result.get("confidence", confidence)
        final_cause = llm_result.get("primary_cause", primary_cause)
        explanation = llm_result.get("explanation", "")
        recommended_action = llm_result.get("recommended_action", "")

        # Step 6 — Estimate payout if claim triggered
        payout = {}
        if claim_triggered:
            payout = estimate_payout(
                zone,
                scores["weather_score"],
                scores["traffic_score"],
                scores["social_score"],
                final_confidence,
            )

        # Step 7 — Store risk signal in DB
        risk_signal = RiskSignal(
            worker_id=worker_id,
            zone=zone,
            weather_score=scores["weather_score"],
            weather_level=scores["weather_level"],
            traffic_score=scores["traffic_score"],
            traffic_level=scores["traffic_level"],
            social_score=scores["social_score"],
            social_level=scores["social_level"],
            source_weather=signals["weather"].get("data", {}).get("source", "unknown"),
            source_traffic=signals["traffic"].get("data", {}).get("source", "unknown"),
            source_social="reddit+newsapi",
        )
        self.db.add(risk_signal)
        await self.db.flush()

        overall_level = classify_risk(fused)

        return {
            "worker_id": worker_id,
            "zone": zone,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reasoning_source": llm_response["status"],

            # Scores
            "scores": scores,
            "fused_score": fused,
            "overall_risk_level": overall_level,

            # Decision
            "claim_triggered": claim_triggered,
            "confidence": final_confidence,
            "primary_cause": final_cause,
            "explanation": explanation,
            "recommended_action": recommended_action,
            "claim_recommended": claim_triggered,

            # Payout details
            "payout": payout if payout else None,

            # Signal breakdown for dashboard
            "weather": {
                "score": scores["weather_score"],
                "level": scores["weather_level"],
                "details": signals["weather"].get("data", {}).get("sub_scores", {}),
            },
            "traffic": {
                "score": scores["traffic_score"],
                "level": scores["traffic_level"],
                "details": signals["traffic"].get("data", {}).get("sub_scores", {}),
            },
            "social": {
                "score": scores["social_score"],
                "level": scores["social_level"],
                "details": signals["social"].get("data", {}).get("sub_scores", {}),
            },

            # Raw for debugging
            "risk_signal_id": risk_signal.id,
        }
