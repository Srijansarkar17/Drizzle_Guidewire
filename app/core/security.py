"""
Security — JWT token generation, verification, and auth middleware.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

log = logging.getLogger("drizzle.security")

security_scheme = HTTPBearer()


# ─────────────────────────────────────────────────────────────────
# TOKEN HELPERS
# ─────────────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    email: str,
    role: str = "worker",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=settings.JWT_EXPIRATION_HOURS))

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises on invalid/expired."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )


# ─────────────────────────────────────────────────────────────────
# FASTAPI DEPENDENCIES
# ─────────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Extract and validate the current user from the Bearer token.
    Returns a dict with user_id, email, role.
    Also verifies the user still exists in the database.
    """
    token = credentials.credentials
    payload = decode_token(token)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Import here to avoid circular imports
    from app.models.models import AuthUser
    result = await db.execute(
        select(AuthUser).where(AuthUser.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return {
        "user_id": str(user.id),
        "email": user.email,
        "role": payload.get("role", "worker"),
    }


async def require_worker(current_user: dict = Depends(get_current_user)) -> dict:
    """Ensure the current user has the 'worker' role."""
    if current_user["role"] not in ("worker", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Worker access required",
        )
    return current_user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Ensure the current user has the 'admin' role."""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
