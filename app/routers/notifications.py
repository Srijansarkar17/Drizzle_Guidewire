"""
Notifications Router — GET /notifications, POST /notifications/read/{id}
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Notification
from app.schemas.schemas import (
    NotificationResponse,
    NotificationListResponse,
    SuccessResponse,
)

log = logging.getLogger("drizzle.router.notifications")

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all notifications for the authenticated user.
    Sorted by newest first. Includes unread count.
    """
    user_id = current_user["user_id"]

    # Get all notifications
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    notifications = result.scalars().all()

    # Count unread
    unread_result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,
        )
    )
    unread_count = unread_result.scalar() or 0

    return NotificationListResponse(
        notifications=[
            NotificationResponse(
                id=n.id,
                title=n.title,
                message=n.message,
                notification_type=n.notification_type,
                is_read=n.is_read,
                created_at=n.created_at,
            )
            for n in notifications
        ],
        total=len(notifications),
        unread_count=unread_count,
    )


@router.post("/read/{notification_id}", response_model=SuccessResponse)
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a notification as read.
    """
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user["user_id"],
        )
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found.",
        )

    notification.is_read = True
    await db.flush()

    log.info(f"Notification {notification_id} marked as read")

    return SuccessResponse(
        message="Notification marked as read",
        data={"notification_id": notification_id},
    )
