"""
Policy Service — calculate premiums, create/manage policies.
Aligned with SQL DDL schema (coverage_type, coverage_days, sum_insured, premium, zone_multiplier).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Policy, Worker

log = logging.getLogger("drizzle.policy_service")

# Zone risk multipliers for premium calculation
ZONE_RISK_MULTIPLIERS = {
    "mumbai": 1.3,
    "delhi": 1.25,
    "chennai": 1.2,
    "bangalore": 1.15,
    "hyderabad": 1.1,
    "kolkata": 1.2,
    "noida": 1.15,
    "pune": 1.1,
    "jaipur": 1.05,
    "default": 1.0,
}

# Vehicle risk multipliers
VEHICLE_RISK = {
    "bike": 1.2,
    "scooter": 1.15,
    "cycle": 1.3,
    "car": 1.0,
    "default": 1.1,
}


class PolicyService:
    """Handles policy calculation, creation, and management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_premium(
        self,
        zone: Optional[str] = None,
        vehicle_type: Optional[str] = None,
        daily_income_estimate: Optional[int] = None,
        coverage_type: str = "standard",
    ) -> dict:
        """
        Calculate premium based on zone risk, vehicle type, and income.
        Returns coverage details without creating a policy.
        """
        base_income = daily_income_estimate or 1000

        # Zone multiplier
        zone_key = (zone or "").lower().split("-")[-1].strip()
        zone_mult = ZONE_RISK_MULTIPLIERS.get(zone_key, ZONE_RISK_MULTIPLIERS["default"])

        # Vehicle multiplier
        veh_key = (vehicle_type or "").lower()
        veh_mult = VEHICLE_RISK.get(veh_key, VEHICLE_RISK["default"])

        # Sum insured (max daily payout) = 80% of daily income
        sum_insured = round(base_income * 0.80, 2)

        # Premium calculation based on coverage type
        coverage_days = 30
        if coverage_type == "premium":
            base_rate = 0.05
            coverage_days = 30
        else:
            base_rate = 0.03
            coverage_days = 30

        monthly_coverage = sum_insured * coverage_days
        premium = round(monthly_coverage * base_rate * zone_mult * veh_mult, 2)

        # Estimated claims per month (based on zone risk)
        est_claims = max(2, int(5 * zone_mult))

        log.info(
            f"Premium calculated: zone={zone} vehicle={vehicle_type} "
            f"income={base_income} → premium=₹{premium}/month"
        )

        return {
            "sum_insured": sum_insured,
            "premium": premium,
            "coverage_type": coverage_type,
            "coverage_days": coverage_days,
            "zone_multiplier": zone_mult,
            "estimated_monthly_claims": est_claims,
            "coverage_details": {
                "coverage_type": coverage_type,
                "max_daily_payout": sum_insured,
                "income_coverage_ratio": 0.80,
                "zone_risk_multiplier": zone_mult,
                "vehicle_risk_multiplier": veh_mult,
                "base_daily_income": base_income,
            },
        }

    async def create_policy(
        self,
        worker_id: str,
        coverage_type: str = "standard",
        coverage_days: int = 30,
        sum_insured: float = 800.0,
        premium: float = 360.0,
        zone_multiplier: float = 1.0,
    ) -> Policy:
        """
        Create a new policy for a worker.
        Validates worker exists and has no conflicting active policy.
        """
        # Check worker exists
        result = await self.db.execute(
            select(Worker).where(Worker.id == worker_id)
        )
        worker = result.scalar_one_or_none()
        if not worker:
            raise ValueError("Worker profile not found. Create a profile first.")

        # Check for existing active policy
        result = await self.db.execute(
            select(Policy).where(
                Policy.worker_id == worker_id,
                Policy.status == "active",
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise ValueError(
                f"Worker already has an active policy (ID: {existing.id}). "
                "Cancel existing policy before creating a new one."
            )

        # Set dates
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(days=coverage_days)

        policy = Policy(
            worker_id=worker_id,
            coverage_type=coverage_type,
            coverage_days=coverage_days,
            sum_insured=sum_insured,
            premium=premium,
            zone_multiplier=zone_multiplier,
            status="active",
            start_date=now,
            end_date=end_date,
        )
        self.db.add(policy)
        await self.db.flush()

        log.info(f"Policy created: {policy.id} for worker {worker_id}")
        return policy

    async def get_worker_policies(self, worker_id: str) -> List[Policy]:
        """Get all policies for a worker."""
        result = await self.db.execute(
            select(Policy)
            .where(Policy.worker_id == worker_id)
            .order_by(Policy.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_policy_by_id(self, policy_id: str, worker_id: str) -> Optional[Policy]:
        """Get a specific policy by ID, scoped to worker."""
        result = await self.db.execute(
            select(Policy).where(
                Policy.id == policy_id,
                Policy.worker_id == worker_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_policy(self, worker_id: str) -> Optional[Policy]:
        """Get the currently active policy for a worker."""
        result = await self.db.execute(
            select(Policy).where(
                Policy.worker_id == worker_id,
                Policy.status == "active",
            )
        )
        return result.scalar_one_or_none()
