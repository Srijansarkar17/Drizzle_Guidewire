"""
Auth Service — signup, login, session management.
Aligned with SQL DDL schema.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.core.config import settings
from app.models.models import AuthUser, AuthSession

log = logging.getLogger("drizzle.auth_service")


class AuthService:
    """Handles user authentication — signup, login, session tracking."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def signup(
        self,
        email: str,
        password: str,
        phone: Optional[str] = None,
        role: str = "worker",
    ) -> dict:
        """
        Create a new user account.
        Password stored as plain text per requirement.
        """
        # Check if email already exists
        result = await self.db.execute(
            select(AuthUser).where(AuthUser.email == email)
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise ValueError(f"User with email '{email}' already exists")

        # Create user
        user = AuthUser(
            email=email,
            password=password,  # Plain text as required
            phone=phone,
            role=role,
        )
        self.db.add(user)
        await self.db.flush()

        # Generate token
        token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
        )

        # Create session
        session = AuthSession(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS),
        )
        self.db.add(session)
        await self.db.flush()

        log.info(f"New user signed up: {email} (role={role})")

        return {
            "user_id": str(user.id),
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "token": token,
            "message": "Account created successfully",
        }

    async def login(self, email: str, password: str) -> dict:
        """
        Authenticate user with email + password.
        Returns JWT token on success.
        """
        result = await self.db.execute(
            select(AuthUser).where(AuthUser.email == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("Invalid email or password")

        # Plain text password comparison per requirement
        if user.password != password:
            raise ValueError("Invalid email or password")

        if not user.is_active:
            raise ValueError("Account is deactivated")

        # Generate token
        token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
        )

        # Create session
        session = AuthSession(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS),
        )
        self.db.add(session)
        await self.db.flush()

        log.info(f"User logged in: {email}")

        return {
            "user_id": str(user.id),
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "token": token,
            "message": "Login successful",
        }

    async def get_user_profile(self, user_id: str) -> dict:
        """Fetch user profile by ID."""
        result = await self.db.execute(
            select(AuthUser).where(AuthUser.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        return {
            "user_id": str(user.id),
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }
