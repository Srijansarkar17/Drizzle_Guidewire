"""
Risk Router — GET /risk/live
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Worker
from app.services.risk_service import RiskService
from app.utils.geo import get_zone_from_gps

log = logging.getLogger("drizzle.router.risk")

router = APIRouter(prefix="/risk", tags=["Risk Assessment"])


@router.get("/live")
async def get_live_risk(
    lat: float = Query(None, description="Latitude"),
    lon: float = Query(None, description="Longitude"),
    zone: str = Query(None, description="Zone name (e.g. OMR-Chennai)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get live risk assessment by calling all 3 MCP servers.

    If lat/lon not provided, worker's registered location is used.
    Returns fused score, individual server scores, and claim recommendation.
    """
    # Find worker — Worker.id IS auth_users.id (shared PK)
    result = await db.execute(
        select(Worker).where(Worker.id == current_user["user_id"])
    )
    worker = result.scalar_one_or_none()

    # Resolve coordinates
    if lat is None or lon is None:
        if worker and worker.gps_lat and worker.gps_lon:
            lat = worker.gps_lat
            lon = worker.gps_lon
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "lat and lon are required. Either provide them as query params "
                    "or set them in your worker profile."
                ),
            )

    zone = get_zone_from_gps(lat, lon)
    worker_id = worker.id if worker else None

    try:
        service = RiskService(db)
        risk_result = await service.assess_live_risk(
            lat=lat,
            lon=lon,
            worker_id=worker_id,
            zone=zone,
        )
        return risk_result
    except Exception as e:
        log.error(f"Live risk assessment failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Risk assessment failed: {str(e)}",
        )
