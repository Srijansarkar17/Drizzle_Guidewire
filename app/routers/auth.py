"""
Auth Router — POST /auth/signup, POST /auth/login, GET /auth/me
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.schemas import (
    SignupRequest,
    LoginRequest,
    AuthResponse,
    UserProfile,
)
from app.services.auth_service import AuthService

log = logging.getLogger("drizzle.router.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new user account.
    Returns JWT token for immediate authentication.
    """
    try:
        service = AuthService(db)
        result = await service.signup(
            email=req.email,
            password=req.password,
            phone=req.phone,
        )
        return AuthResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with email + password.
    Returns JWT token on success.
    """
    try:
        service = AuthService(db)
        result = await service.login(
            email=req.email,
            password=req.password,
        )
        return AuthResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.get("/me", response_model=UserProfile)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current authenticated user's profile.
    Requires Bearer token.
    """
    try:
        service = AuthService(db)
        result = await service.get_user_profile(current_user["user_id"])
        return UserProfile(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
