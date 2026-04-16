"""
Claims Router — POST /claims/trigger, GET /claims/my, GET /claims/{id}
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Worker
from app.schemas.schemas import ClaimTriggerRequest
from app.services.claim_service import ClaimService
from app.utils.geo import get_zone_from_gps

log = logging.getLogger("drizzle.router.claims")

router = APIRouter(prefix="/claims", tags=["Claims"])


@router.post("/trigger")
async def trigger_claim(
    req: ClaimTriggerRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a claim assessment for the authenticated worker.

    Full flow:
    1. Validates active policy
    2. Calls all 3 MCP servers for risk assessment
    3. LLM reasoning (or formula fallback)
    4. Fraud check
    5. Payout calculation if triggered
    6. Saves claim + creates notification
    """
    # Find worker — Worker.id IS auth_users.id (shared PK)
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
        service = ClaimService(db)
        claim_result = await service.trigger_claim(
            worker_id=worker.id,
            user_id=current_user["user_id"],
            lat=req.lat,
            lon=req.lon,
            zone=get_zone_from_gps(req.lat, req.lon),
        )
        return claim_result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        log.error(f"Claim trigger failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process claim: {str(e)}",
        )


@router.get("/my")
async def get_my_claims(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all claims for the authenticated worker.
    Returns claims sorted by creation date (newest first).
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

    service = ClaimService(db)
    claims = await service.get_worker_claims(worker.id)

    return {
        "claims": claims,
        "total": len(claims),
    }


@router.get("/{claim_id}")
async def get_claim(
    claim_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific claim by ID.
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

    service = ClaimService(db)
    claim = await service.get_claim_by_id(claim_id, worker.id)

    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found.",
        )

    return claim
