"""
Policies Router — POST /policies/calculate, POST /policies/create,
                  GET /policies/my, GET /policies/{id}
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Worker
from app.schemas.schemas import (
    PolicyCalculateRequest,
    PolicyCalculateResponse,
    PolicyCreateRequest,
    PolicyResponse,
)
from app.services.policy_service import PolicyService

log = logging.getLogger("drizzle.router.policies")

router = APIRouter(prefix="/policies", tags=["Policies"])


@router.post("/calculate", response_model=PolicyCalculateResponse)
async def calculate_premium(
    req: PolicyCalculateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate premium without creating a policy.
    Useful for showing price estimates in the UI.
    """
    service = PolicyService(db)
    result = await service.calculate_premium(
        zone=req.zone,
        vehicle_type=req.vehicle_type,
        daily_income_estimate=req.daily_income_estimate,
        coverage_type=req.coverage_type,
    )
    return PolicyCalculateResponse(**result)


@router.post("/create", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    req: PolicyCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new policy for the authenticated worker.
    Worker must have a profile. Only one active policy allowed.
    """
    # Find worker profile — Worker.id IS auth_users.id
    result = await db.execute(
        select(Worker).where(Worker.id == current_user["user_id"])
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker profile not found. Create one first.",
        )

    try:
        service = PolicyService(db)
        policy = await service.create_policy(
            worker_id=worker.id,
            coverage_type=req.coverage_type,
            coverage_days=req.coverage_days,
            sum_insured=req.sum_insured,
            premium=req.premium,
            zone_multiplier=req.zone_multiplier,
        )

        return PolicyResponse(
            id=policy.id,
            worker_id=policy.worker_id,
            coverage_type=policy.coverage_type,
            coverage_days=policy.coverage_days,
            sum_insured=policy.sum_insured,
            premium=policy.premium,
            zone_multiplier=policy.zone_multiplier,
            status=policy.status,
            start_date=policy.start_date,
            end_date=policy.end_date,
            created_at=policy.created_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )


@router.get("/my", response_model=list[PolicyResponse])
async def get_my_policies(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all policies for the authenticated worker.
    """
    result = await db.execute(
        select(Worker).where(Worker.id == current_user["user_id"])
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker profile not found.",
        )

    service = PolicyService(db)
    policies = await service.get_worker_policies(worker.id)

    return [
        PolicyResponse(
            id=p.id,
            worker_id=p.worker_id,
            coverage_type=p.coverage_type,
            coverage_days=p.coverage_days,
            sum_insured=p.sum_insured,
            premium=p.premium,
            zone_multiplier=p.zone_multiplier,
            status=p.status,
            start_date=p.start_date,
            end_date=p.end_date,
            created_at=p.created_at,
        )
        for p in policies
    ]


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific policy by ID.
    """
    result = await db.execute(
        select(Worker).where(Worker.id == current_user["user_id"])
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker profile not found.",
        )

    service = PolicyService(db)
    policy = await service.get_policy_by_id(policy_id, worker.id)

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found.",
        )

    return PolicyResponse(
        id=policy.id,
        worker_id=policy.worker_id,
        coverage_type=policy.coverage_type,
        coverage_days=policy.coverage_days,
        sum_insured=policy.sum_insured,
        premium=policy.premium,
        zone_multiplier=policy.zone_multiplier,
        status=policy.status,
        start_date=policy.start_date,
        end_date=policy.end_date,
        created_at=policy.created_at,
    )
