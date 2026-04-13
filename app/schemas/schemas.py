"""
Pydantic Schemas — Request/Response validation for all API endpoints.
Aligned with SQL DDL schema column names.
"""

from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, EmailStr, Field


# ═════════════════════════════════════════════════════════════════
# AUTH SCHEMAS
# ═════════════════════════════════════════════════════════════════

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=4, max_length=128)
    phone: Optional[str] = Field(None, max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    user_id: str
    email: str
    phone: Optional[str] = None
    role: str
    token: str
    message: str = "Success"


class UserProfile(BaseModel):
    user_id: str
    email: str
    phone: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime


# ═════════════════════════════════════════════════════════════════
# WORKER SCHEMAS
# ═════════════════════════════════════════════════════════════════

class WorkerProfileCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    zone: Optional[str] = None
    vehicle_type: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    daily_income_estimate: Optional[int] = Field(None, ge=0)


class WorkerProfileResponse(BaseModel):
    id: str
    full_name: str
    phone: Optional[str] = None
    zone: Optional[str] = None
    vehicle_type: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    daily_income_estimate: Optional[int] = None
    total_claims: int = 0
    total_payout: float = 0
    created_at: datetime
    updated_at: datetime


# ═════════════════════════════════════════════════════════════════
# POLICY SCHEMAS
# ═════════════════════════════════════════════════════════════════

class PolicyCalculateRequest(BaseModel):
    zone: Optional[str] = None
    vehicle_type: Optional[str] = None
    daily_income_estimate: Optional[int] = Field(None, ge=0)
    coverage_type: str = "standard"     # standard, premium


class PolicyCalculateResponse(BaseModel):
    sum_insured: float
    premium: float
    coverage_type: str
    coverage_days: int
    zone_multiplier: float
    estimated_monthly_claims: int
    coverage_details: dict


class PolicyCreateRequest(BaseModel):
    coverage_type: str = "standard"
    coverage_days: int = Field(30, gt=0)
    sum_insured: float = Field(..., gt=0)
    premium: float = Field(..., gt=0)
    zone_multiplier: float = Field(1.0, ge=0)


class PolicyResponse(BaseModel):
    id: str
    worker_id: str
    coverage_type: Optional[str] = None
    coverage_days: Optional[int] = None
    sum_insured: Optional[float] = None
    premium: Optional[float] = None
    zone_multiplier: Optional[float] = None
    status: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════
# CLAIM SCHEMAS
# ═════════════════════════════════════════════════════════════════

class ClaimTriggerRequest(BaseModel):
    lat: float
    lon: float
    zone: Optional[str] = None


class ClaimScores(BaseModel):
    weather_score: float
    weather_level: str
    traffic_score: float
    traffic_level: str
    social_score: float
    social_level: str
    fused_score: float


class ClaimPayoutDetail(BaseModel):
    base_daily_income_inr: float
    estimated_actual_income: float
    estimated_income_loss: float
    payout_amount_inr: float
    coverage_percent: float
    disruption_intensity: float


class ClaimResponse(BaseModel):
    id: str
    worker_id: Optional[str] = None
    policy_id: Optional[str] = None
    status: str
    claim_triggered: Optional[bool] = None
    primary_cause: Optional[str] = None
    confidence: Optional[str] = None
    scores: Optional[ClaimScores] = None
    payout: Optional[ClaimPayoutDetail] = None
    payout_amount: float = 0
    explanation: Optional[str] = None
    recommended_action: Optional[str] = None
    reasoning_source: Optional[str] = None
    zone: Optional[str] = None
    created_at: datetime


class ClaimListResponse(BaseModel):
    claims: List[ClaimResponse]
    total: int


# ═════════════════════════════════════════════════════════════════
# RISK SCHEMAS
# ═════════════════════════════════════════════════════════════════

class RiskLiveRequest(BaseModel):
    lat: float
    lon: float
    zone: Optional[str] = None


class RiskSignalResponse(BaseModel):
    worker_id: Optional[str] = None
    zone: Optional[str] = None
    timestamp: str

    weather: dict
    traffic: dict
    social: dict

    fused_score: float
    overall_risk_level: str
    claim_recommended: bool
    confidence: str
    primary_cause: str
    explanation: str


# ═════════════════════════════════════════════════════════════════
# NOTIFICATION SCHEMAS
# ═════════════════════════════════════════════════════════════════

class NotificationResponse(BaseModel):
    id: str
    title: Optional[str] = None
    message: Optional[str] = None
    notification_type: Optional[str] = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]
    total: int
    unread_count: int


# ═════════════════════════════════════════════════════════════════
# GENERIC SCHEMAS
# ═════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    mcp_servers: dict
    timestamp: str


class ErrorResponse(BaseModel):
    detail: str
    status_code: int = 400


class SuccessResponse(BaseModel):
    message: str
    data: Optional[Any] = None
