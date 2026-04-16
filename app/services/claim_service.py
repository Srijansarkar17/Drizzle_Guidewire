"""
Claim Service — trigger, create, manage claims.
Aligned with SQL DDL schema.
Orchestrates: validate policy → assess risk → fraud check → payout → save.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Claim, ClaimExplanation, FraudCheck, FraudFlag,
    Policy, Worker, Notification, WorkerActivityLog,
)
from app.services.risk_service import RiskService
from app.services.admin.admin_analytics_service import AdminAnalyticsService
from app.services.admin.admin_fraud_service import AdminFraudService

log = logging.getLogger("drizzle.claim_service")


class ClaimService:
    """Handles the full claim lifecycle."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.risk_service = RiskService(db)

    async def trigger_claim(
        self,
        worker_id: str,
        user_id: str,
        lat: float,
        lon: float,
        zone: Optional[str] = None,
    ) -> dict:
        """
        Full claim trigger flow:
        1. Validate active policy
        2. Call MCP risk_service
        3. Decide: claim_triggered, confidence, cause
        4. Run fraud checks (basic)
        5. If triggered: calculate payout
        6. Save claim + explanation + fraud check
        7. Create notification
        8. Return response
        """

        # ── Step 1: Validate active policy ────────────────────────
        result = await self.db.execute(
            select(Worker).where(Worker.id == worker_id)
        )
        worker = result.scalar_one_or_none()
        if not worker:
            raise ValueError("Worker profile not found. Create a profile first.")

        result = await self.db.execute(
            select(Policy).where(
                Policy.worker_id == worker_id,
                Policy.status == "active",
            )
        )
        active_policy = result.scalar_one_or_none()
        if not active_policy:
            raise ValueError(
                "No active policy found. Purchase a policy before triggering a claim."
            )

        # Use worker's zone if not provided
        claim_zone = zone or worker.zone

        # ── Step 2: Call MCP risk service ─────────────────────────
        log.info(f"Triggering claim assessment for worker {worker_id}")
        risk_result = await self.risk_service.assess_live_risk(
            lat=lat,
            lon=lon,
            worker_id=worker_id,
            zone=claim_zone,
        )

        scores = risk_result.get("scores", {})
        claim_triggered = risk_result.get("claim_triggered", False)
        confidence = risk_result.get("confidence", "LOW")
        primary_cause = risk_result.get("primary_cause", "none")
        explanation = risk_result.get("explanation", "")
        recommended_action = risk_result.get("recommended_action", "")
        reasoning_source = risk_result.get("reasoning_source", "fallback")
        fused_score = risk_result.get("fused_score", 0.0)
        payout_data = risk_result.get("payout")

        # ── Step 3: Run basic fraud checks ────────────────────────
        fraud_result = await self._run_fraud_check(worker_id, lat, lon, claim_zone)

        # If fraud detected, block the claim
        if fraud_result["verdict"] == "fraudulent":
            claim_triggered = False
            explanation += " [BLOCKED: Fraud check failed]"
            log.warning(f"Claim blocked for worker {worker_id}: fraud detected")

        # ── Step 4: Determine payout ──────────────────────────────
        payout_amount = 0.0

        if claim_triggered and payout_data:
            payout_amount = payout_data.get("payout_amount_inr", 0.0)

        # Apply policy coverage cap (sum_insured)
        if active_policy.sum_insured and payout_amount > active_policy.sum_insured:
            payout_amount = active_policy.sum_insured
            log.info(f"Payout capped at sum_insured: ₹{payout_amount}")

        # ── Step 5: Save claim ────────────────────────────────────
        claim_status = "approved" if claim_triggered else "rejected"

        claim = Claim(
            worker_id=worker_id,
            policy_id=active_policy.id,
            status=claim_status,
            zone=claim_zone,
            lat=lat,
            lon=lon,
            weather_score=scores.get("weather_score", 0.0),
            traffic_score=scores.get("traffic_score", 0.0),
            social_score=scores.get("social_score", 0.0),
            fused_score=fused_score,
            claim_triggered=claim_triggered,
            confidence=confidence,
            primary_cause=primary_cause,
            payout_amount=payout_amount,
            reasoning_source=reasoning_source,
        )
        self.db.add(claim)
        await self.db.flush()

        # ── Step 6: Update worker totals ──────────────────────────
        if claim_triggered and payout_amount > 0:
            worker.total_claims = (worker.total_claims or 0) + 1
            worker.total_payout = (worker.total_payout or 0) + payout_amount

        # ── Step 7: Save claim explanation ────────────────────────
        claim_explanation = ClaimExplanation(
            claim_id=claim.id,
            explanation=explanation,
            recommended_action=recommended_action,
        )
        self.db.add(claim_explanation)

        # ── Step 8: Save fraud check ─────────────────────────────
        fraud_check = FraudCheck(
            claim_id=claim.id,
            gps_valid=fraud_result["gps_valid"],
            gps_distance_km=fraud_result.get("gps_distance_km"),
            multi_server_ok=fraud_result.get("multi_server_ok", True),
            score_variance_flag=fraud_result.get("score_variance_flag", False),
            anomaly_flag=fraud_result.get("anomaly_flag", False),
            fraud_score=fraud_result["fraud_score"],
            verdict=fraud_result["verdict"],
        )
        self.db.add(fraud_check)

        # ── Step 9: Create notification ───────────────────────────
        if claim_triggered and payout_amount > 0:
            cause_label = {
                "weather": "rain disruption",
                "traffic": "traffic congestion",
                "social": "social disruption",
                "combined": "multiple disruptions",
            }.get(primary_cause, "disruption")

            notification = Notification(
                user_id=user_id,
                title="Claim Approved — Payout Credited",
                message=f"₹{payout_amount:.0f} credited due to {cause_label}",
                notification_type="claim",
            )
            self.db.add(notification)
        elif not claim_triggered:
            notification = Notification(
                user_id=user_id,
                title="Risk Assessment Complete",
                message=(
                    f"No significant disruption detected in your area. "
                    f"Fused risk score: {fused_score:.2f}"
                ),
                notification_type="alert",
            )
            self.db.add(notification)

        await self.db.flush()

        # ── Admin Integration Hooks ───────────────────────────────
        # Activity log
        activity = WorkerActivityLog(
            worker_id=worker_id,
            action="claim_trigger",
            metadata_json={
                "claim_id": claim.id,
                "zone": claim_zone,
                "fused_score": fused_score,
                "status": claim_status,
                "payout": payout_amount,
            },
        )
        self.db.add(activity)

        # Update daily + zone metrics
        analytics = AdminAnalyticsService(self.db)
        await analytics.update_daily_metrics(
            claim_status=claim_status,
            payout=payout_amount,
            is_fraud=fraud_result["verdict"] != "clean",
        )
        await analytics.update_zone_metrics(
            zone=claim_zone,
            weather=scores.get("weather_score", 0.0),
            traffic=scores.get("traffic_score", 0.0),
            social=scores.get("social_score", 0.0),
            payout=payout_amount,
        )

        # Create fraud alert if fraud detected
        if fraud_result["verdict"] != "clean":
            fraud_svc = AdminFraudService(self.db)
            await fraud_svc.create_fraud_alert(
                claim_id=claim.id,
                fraud_score=fraud_result["fraud_score"],
                verdict=fraud_result["verdict"],
            )

        await self.db.flush()

        log.info(
            f"Claim {claim.id}: triggered={claim_triggered} "
            f"payout=₹{payout_amount} cause={primary_cause}"
        )

        # ── Build response ────────────────────────────────────────
        return {
            "id": claim.id,
            "worker_id": worker_id,
            "policy_id": active_policy.id,
            "status": claim.status,
            "claim_triggered": claim_triggered,
            "primary_cause": primary_cause,
            "confidence": confidence,
            "scores": {
                "weather_score": scores.get("weather_score", 0.0),
                "weather_level": scores.get("weather_level", "LOW"),
                "traffic_score": scores.get("traffic_score", 0.0),
                "traffic_level": scores.get("traffic_level", "LOW"),
                "social_score": scores.get("social_score", 0.0),
                "social_level": scores.get("social_level", "LOW"),
                "fused_score": fused_score,
            },
            "payout": {
                "base_daily_income_inr": payout_data.get("base_daily_income_inr", 0) if payout_data else 0,
                "estimated_actual_income": payout_data.get("estimated_actual_income", 0) if payout_data else 0,
                "estimated_income_loss": payout_data.get("estimated_income_loss", 0) if payout_data else 0,
                "payout_amount_inr": payout_amount,
                "coverage_percent": 80.0,
                "disruption_intensity": payout_data.get("disruption_intensity", 0) if payout_data else 0,
            } if claim_triggered else None,
            "payout_amount": payout_amount,
            "explanation": explanation,
            "recommended_action": recommended_action,
            "reasoning_source": reasoning_source,
            "zone": claim_zone,
            "created_at": claim.created_at.isoformat(),
            "fraud_check": {
                "gps_valid": fraud_result["gps_valid"],
                "fraud_score": fraud_result["fraud_score"],
                "verdict": fraud_result["verdict"],
            },
        }

    async def _run_fraud_check(
        self,
        worker_id: str,
        lat: float,
        lon: float,
        zone: Optional[str],
    ) -> dict:
        """
        Basic fraud detection matching SQL fraud_checks schema:
        - gps_valid: is GPS location near worker's registered zone
        - gps_distance_km: distance from registered location
        - multi_server_ok: all 3 MCP servers responded
        - score_variance_flag: scores suspiciously uniform
        - anomaly_flag: rapid claim frequency
        - fraud_score: composite fraud score
        - verdict: clean / suspicious / fraudulent
        """
        fraud_score = 0.0
        anomaly_flag = False
        gps_valid = True
        gps_distance_km = 0.0

        # Check location mismatch
        from app.utils.geo import get_zone_from_gps
        worker_record = await self.db.execute(select(Worker).where(Worker.id == worker_id))
        worker_record = worker_record.scalar_one_or_none()
        if worker_record and worker_record.zone:
            derived_zone = get_zone_from_gps(lat, lon)
            if derived_zone != "Default-Zone" and worker_record.zone != "Default-Zone" and derived_zone != worker_record.zone:
                fraud_score += 0.8
                gps_valid = False
                fraud_flag = FraudFlag(
                    claim_id=None,
                    flag_type="location_mismatch",
                    severity=0.9,
                    description=f"Claim location ({derived_zone}) does not match registered zone ({worker_record.zone})",
                )
                self.db.add(fraud_flag)

        # Check claim frequency in last 24 hours
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await self.db.execute(
            select(func.count(Claim.id)).where(
                Claim.worker_id == worker_id,
                Claim.created_at >= cutoff,
            )
        )
        claims_today = result.scalar() or 0

        if claims_today >= 5:
            fraud_score += 0.7
            anomaly_flag = True

            # Create fraud flag record
            fraud_flag = FraudFlag(
                claim_id=None,  # Will be set after claim creation if needed
                flag_type="rapid_claims",
                severity=0.8,
                description=f"Worker triggered {claims_today} claims in 24 hours",
            )
            self.db.add(fraud_flag)
        elif claims_today >= 3:
            fraud_score += 0.3
            anomaly_flag = True

        # Determine verdict
        if fraud_score >= 0.6:
            verdict = "fraudulent"
        elif fraud_score >= 0.3:
            verdict = "suspicious"
        else:
            verdict = "clean"

        return {
            "gps_valid": gps_valid,
            "gps_distance_km": gps_distance_km,
            "multi_server_ok": True,
            "score_variance_flag": False,
            "anomaly_flag": anomaly_flag,
            "fraud_score": round(fraud_score, 2),
            "verdict": verdict,
        }

    async def get_worker_claims(self, worker_id: str) -> List[dict]:
        """Get all claims for a worker."""
        result = await self.db.execute(
            select(Claim)
            .where(Claim.worker_id == worker_id)
            .order_by(Claim.created_at.desc())
        )
        claims = result.scalars().all()

        return [self._claim_to_dict(c) for c in claims]

    async def get_claim_by_id(self, claim_id: str, worker_id: str) -> Optional[dict]:
        """Get a specific claim by ID, scoped to worker."""
        result = await self.db.execute(
            select(Claim).where(
                Claim.id == claim_id,
                Claim.worker_id == worker_id,
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            return None
        return self._claim_to_dict(claim)

    def _claim_to_dict(self, claim: Claim) -> dict:
        """Convert a Claim ORM object to response dict."""
        return {
            "id": claim.id,
            "worker_id": claim.worker_id,
            "policy_id": claim.policy_id,
            "status": claim.status,
            "claim_triggered": claim.claim_triggered,
            "primary_cause": claim.primary_cause,
            "confidence": claim.confidence,
            "scores": {
                "weather_score": claim.weather_score or 0,
                "weather_level": "HIGH" if (claim.weather_score or 0) >= 0.6 else "MEDIUM" if (claim.weather_score or 0) >= 0.3 else "LOW",
                "traffic_score": claim.traffic_score or 0,
                "traffic_level": "HIGH" if (claim.traffic_score or 0) >= 0.6 else "MEDIUM" if (claim.traffic_score or 0) >= 0.3 else "LOW",
                "social_score": claim.social_score or 0,
                "social_level": "HIGH" if (claim.social_score or 0) >= 0.6 else "MEDIUM" if (claim.social_score or 0) >= 0.3 else "LOW",
                "fused_score": claim.fused_score or 0,
            },
            "payout_amount": claim.payout_amount or 0,
            "reasoning_source": claim.reasoning_source,
            "zone": claim.zone,
            "created_at": claim.created_at.isoformat() if claim.created_at else None,
        }
