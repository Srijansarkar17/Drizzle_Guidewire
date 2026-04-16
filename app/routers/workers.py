"""
Workers Router — POST /workers/profile, GET /workers/me
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Worker
from app.utils.geo import get_zone_from_gps
from app.schemas.schemas import (
    WorkerProfileCreate,
    WorkerProfileResponse,
)

log = logging.getLogger("drizzle.router.workers")

router = APIRouter(prefix="/workers", tags=["Workers"])


@router.post("/profile", response_model=WorkerProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_worker_profile(
    req: WorkerProfileCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or update worker profile for the authenticated user.
    Each user can have exactly one worker profile (shared PK with auth_users).
    """
    user_id = current_user["user_id"]

    # Ensure phone uniqueness to prevent duplicate workers
    if req.phone:
        phone_check = await db.execute(
            select(Worker).where(Worker.phone == req.phone, Worker.id != user_id)
        )
        if phone_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered to another worker."
            )

    # Check if profile already exists — Worker.id IS auth_users.id (shared PK)
    result = await db.execute(
        select(Worker).where(Worker.id == user_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing profile
        existing.full_name = req.full_name
        existing.phone = req.phone
        existing.vehicle_type = req.vehicle_type
        existing.zone = get_zone_from_gps(req.gps_lat, req.gps_lon) if req.gps_lat and req.gps_lon else req.zone
        existing.gps_lat = req.gps_lat
        existing.gps_lon = req.gps_lon
        if req.daily_income_estimate is not None:
            existing.daily_income_estimate = req.daily_income_estimate

        await db.flush()
        log.info(f"Worker profile updated: user_id={user_id}")
        worker = existing
    else:
        # Create new profile — id = user_id (shared primary key)
        worker = Worker(
            id=user_id,
            full_name=req.full_name,
            phone=req.phone,
            vehicle_type=req.vehicle_type,
            zone=get_zone_from_gps(req.gps_lat, req.gps_lon) if req.gps_lat and req.gps_lon else req.zone,
            gps_lat=req.gps_lat,
            gps_lon=req.gps_lon,
            daily_income_estimate=req.daily_income_estimate or 1000,
        )
        db.add(worker)
        await db.flush()
        log.info(f"Worker profile created: user_id={user_id}")

    return WorkerProfileResponse(
        id=worker.id,
        full_name=worker.full_name,
        phone=worker.phone,
        zone=worker.zone,
        vehicle_type=worker.vehicle_type,
        gps_lat=worker.gps_lat,
        gps_lon=worker.gps_lon,
        daily_income_estimate=worker.daily_income_estimate,
        total_claims=worker.total_claims or 0,
        total_payout=worker.total_payout or 0,
        created_at=worker.created_at,
        updated_at=worker.updated_at,
    )


@router.get("/me", response_model=WorkerProfileResponse)
async def get_worker_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the worker profile for the authenticated user.
    """
    result = await db.execute(
        select(Worker).where(Worker.id == current_user["user_id"])
    )
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker profile not found. Create one first using POST /workers/profile",
        )

    return WorkerProfileResponse(
        id=worker.id,
        full_name=worker.full_name,
        phone=worker.phone,
        zone=worker.zone,
        vehicle_type=worker.vehicle_type,
        gps_lat=worker.gps_lat,
        gps_lon=worker.gps_lon,
        daily_income_estimate=worker.daily_income_estimate,
        total_claims=worker.total_claims or 0,
        total_payout=worker.total_payout or 0,
        created_at=worker.created_at,
        updated_at=worker.updated_at,
    )
