"""
Admin Analytics Service — Dashboard stats, daily/zone metrics, trends.
"""

import logging
from datetime import datetime, timezone, date

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Worker, Policy, Claim, FraudAlert, FraudCheck,
    WorkerActivityLog, DailyMetric, ZoneMetric, RiskSignal,
)

log = logging.getLogger("drizzle.admin.analytics")


class AdminAnalyticsService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self) -> dict:
        """Aggregate control tower stats."""
        today = date.today()

        total_workers = (await self.db.execute(
            select(func.count(Worker.id))
        )).scalar() or 0

        active_policies = (await self.db.execute(
            select(func.count(Policy.id)).where(Policy.status == "active")
        )).scalar() or 0

        claims_today = (await self.db.execute(
            select(func.count(Claim.id)).where(
                func.date(Claim.created_at) == today
            )
        )).scalar() or 0

        payout_today = (await self.db.execute(
            select(func.coalesce(func.sum(Claim.payout_amount), 0)).where(
                func.date(Claim.created_at) == today,
                Claim.status == "approved",
            )
        )).scalar() or 0.0

        fraud_alerts_count = (await self.db.execute(
            select(func.count(FraudAlert.id)).where(FraudAlert.is_resolved == False)
        )).scalar() or 0

        # Recent activity
        result = await self.db.execute(
            select(WorkerActivityLog)
            .order_by(WorkerActivityLog.created_at.desc())
            .limit(10)
        )
        logs = result.scalars().all()

        recent_activity = []
        for l in logs:
            recent_activity.append({
                "id": l.id,
                "worker_id": l.worker_id,
                "action": l.action,
                "metadata": l.metadata_json,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            })

        return {
            "total_workers": total_workers,
            "active_policies": active_policies,
            "claims_today": claims_today,
            "total_payout_today": float(payout_today),
            "fraud_alerts_count": fraud_alerts_count,
            "recent_activity": recent_activity,
        }

    async def get_analytics_overview(self) -> dict:
        """Trends, top zones, payout distribution."""

        # Daily trends (last 30 days)
        result = await self.db.execute(
            select(DailyMetric)
            .order_by(DailyMetric.date.desc())
            .limit(30)
        )
        daily = result.scalars().all()
        daily_trends = [
            {
                "date": str(d.date) if d.date else None,
                "total_claims": d.total_claims or 0,
                "approved_claims": d.approved_claims or 0,
                "rejected_claims": d.rejected_claims or 0,
                "total_payout": d.total_payout or 0.0,
                "fraud_count": d.fraud_count or 0,
            }
            for d in daily
        ]

        # Top zones by claims
        result = await self.db.execute(
            select(
                Claim.zone,
                func.count(Claim.id).label("claim_count"),
                func.coalesce(func.sum(Claim.payout_amount), 0).label("total_payout"),
            )
            .where(Claim.zone.isnot(None), Claim.status == "approved")
            .group_by(Claim.zone)
            .order_by(func.count(Claim.id).desc())
            .limit(10)
        )
        top_zones = [
            {"zone": row[0], "claim_count": row[1], "total_payout": float(row[2])}
            for row in result.all()
        ]

        # Payout distribution
        total_approved = (await self.db.execute(
            select(func.count(Claim.id)).where(Claim.status == "approved")
        )).scalar() or 0
        total_rejected = (await self.db.execute(
            select(func.count(Claim.id)).where(Claim.status == "rejected")
        )).scalar() or 0
        total_payout = (await self.db.execute(
            select(func.coalesce(func.sum(Claim.payout_amount), 0)).where(Claim.status == "approved")
        )).scalar() or 0.0

        # Summary
        total_claims = (await self.db.execute(
            select(func.count(Claim.id))
        )).scalar() or 0

        return {
            "daily_trends": daily_trends,
            "top_zones": top_zones,
            "payout_distribution": {
                "approved": total_approved,
                "rejected": total_rejected,
                "total_payout": float(total_payout),
            },
            "summary": {
                "total_claims": total_claims,
                "approval_rate": round(total_approved / max(total_claims, 1) * 100, 1),
                "avg_payout": round(float(total_payout) / max(total_approved, 1), 2),
            },
        }

    async def update_daily_metrics(self, claim_status: str, payout: float, is_fraud: bool):
        """Called after every claim creation to update daily_metrics."""
        today = date.today()

        result = await self.db.execute(
            select(DailyMetric).where(DailyMetric.date == today)
        )
        metric = result.scalar_one_or_none()

        if metric:
            metric.total_claims = (metric.total_claims or 0) + 1
            if claim_status == "approved":
                metric.approved_claims = (metric.approved_claims or 0) + 1
                metric.total_payout = (metric.total_payout or 0) + payout
            else:
                metric.rejected_claims = (metric.rejected_claims or 0) + 1
            if is_fraud:
                metric.fraud_count = (metric.fraud_count or 0) + 1
        else:
            metric = DailyMetric(
                date=today,
                total_claims=1,
                approved_claims=1 if claim_status == "approved" else 0,
                rejected_claims=1 if claim_status != "approved" else 0,
                total_payout=payout if claim_status == "approved" else 0,
                fraud_count=1 if is_fraud else 0,
            )
            self.db.add(metric)

        await self.db.flush()

    async def update_zone_metrics(self, zone: str, weather: float, traffic: float, social: float, payout: float):
        """Called after every claim to update zone_metrics."""
        if not zone:
            return

        today = date.today()

        result = await self.db.execute(
            select(ZoneMetric).where(
                ZoneMetric.zone == zone,
                ZoneMetric.date == today,
            )
        )
        metric = result.scalar_one_or_none()

        if metric:
            n = metric.total_claims or 0
            # Running average
            metric.avg_weather_score = ((metric.avg_weather_score or 0) * n + weather) / (n + 1)
            metric.avg_traffic_score = ((metric.avg_traffic_score or 0) * n + traffic) / (n + 1)
            metric.avg_social_score = ((metric.avg_social_score or 0) * n + social) / (n + 1)
            metric.total_claims = n + 1
            metric.total_payout = (metric.total_payout or 0) + payout
        else:
            metric = ZoneMetric(
                zone=zone,
                date=today,
                avg_weather_score=weather,
                avg_traffic_score=traffic,
                avg_social_score=social,
                total_claims=1,
                total_payout=payout,
            )
            self.db.add(metric)

        await self.db.flush()

    async def get_zone_risk_aggregation(self) -> list:
        """Aggregate zone-level risk from risk_signals."""
        result = await self.db.execute(
            select(
                RiskSignal.zone,
                func.avg(RiskSignal.weather_score).label("avg_weather"),
                func.avg(RiskSignal.traffic_score).label("avg_traffic"),
                func.avg(RiskSignal.social_score).label("avg_social"),
                func.count(RiskSignal.id).label("signal_count"),
            )
            .where(RiskSignal.zone.isnot(None))
            .group_by(RiskSignal.zone)
            .order_by(func.count(RiskSignal.id).desc())
        )
        return [
            {
                "zone": row[0],
                "avg_weather": round(float(row[1] or 0), 3),
                "avg_traffic": round(float(row[2] or 0), 3),
                "avg_social": round(float(row[3] or 0), 3),
                "signal_count": row[4],
            }
            for row in result.all()
        ]
