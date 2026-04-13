"""
SQLAlchemy ORM Models — EXACTLY matching the SQL schema for Drizzle.
All column names, types, and relationships match the provided DDL.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def gen_uuid():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────
# 1. AUTH USERS
# ─────────────────────────────────────────────────────────────────

class AuthUser(Base):
    __tablename__ = "auth_users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(Text, unique=True, nullable=False, index=True)
    phone = Column(Text, nullable=True)
    password = Column(Text, nullable=False)          # Plain text per requirement
    role = Column(Text, default="worker")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    sessions = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")
    worker = relationship("Worker", back_populates="user", uselist=False, cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────
# 2. AUTH SESSIONS
# ─────────────────────────────────────────────────────────────────

class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=True)
    token = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    user = relationship("AuthUser", back_populates="sessions")


# ─────────────────────────────────────────────────────────────────
# 3. WORKERS
# workers.id = auth_users.id  (shared primary key, 1:1)
# ─────────────────────────────────────────────────────────────────

class Worker(Base):
    __tablename__ = "workers"

    id = Column(String, ForeignKey("auth_users.id", ondelete="CASCADE"), primary_key=True)
    full_name = Column(Text, nullable=False)
    phone = Column(Text, nullable=True)
    zone = Column(Text, nullable=True)
    vehicle_type = Column(Text, nullable=True)
    gps_lat = Column(Float, nullable=True)
    gps_lon = Column(Float, nullable=True)
    daily_income_estimate = Column(Integer, nullable=True)

    total_claims = Column(Integer, default=0)
    total_payout = Column(Float, default=0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    user = relationship("AuthUser", back_populates="worker")
    policies = relationship("Policy", back_populates="worker", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="worker", cascade="all, delete-orphan")
    risk_signals = relationship("RiskSignal", back_populates="worker", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────
# 4. POLICIES
# ─────────────────────────────────────────────────────────────────

class Policy(Base):
    __tablename__ = "policies"

    id = Column(String, primary_key=True, default=gen_uuid)
    worker_id = Column(String, ForeignKey("workers.id", ondelete="CASCADE"), nullable=True)

    coverage_type = Column(Text, nullable=True)
    coverage_days = Column(Integer, nullable=True)
    sum_insured = Column(Float, nullable=True)

    premium = Column(Float, nullable=True)
    zone_multiplier = Column(Float, nullable=True)

    status = Column(Text, default="active")     # active / expired / cancelled

    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    worker = relationship("Worker", back_populates="policies")
    claims = relationship("Claim", back_populates="policy", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────
# 5. CLAIMS
# ─────────────────────────────────────────────────────────────────

class Claim(Base):
    __tablename__ = "claims"

    id = Column(String, primary_key=True, default=gen_uuid)

    policy_id = Column(String, ForeignKey("policies.id", ondelete="CASCADE"), nullable=True)
    worker_id = Column(String, ForeignKey("workers.id", ondelete="CASCADE"), nullable=True)

    zone = Column(Text, nullable=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    weather_score = Column(Float, nullable=True)
    traffic_score = Column(Float, nullable=True)
    social_score = Column(Float, nullable=True)

    fused_score = Column(Float, nullable=True)

    claim_triggered = Column(Boolean, nullable=True)
    confidence = Column(Text, nullable=True)
    primary_cause = Column(Text, nullable=True)

    status = Column(Text, default="pending")    # pending / approved / rejected / flagged / paid

    payout_amount = Column(Float, default=0)

    reasoning_source = Column(Text, nullable=True)   # rule_engine / llm

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    worker = relationship("Worker", back_populates="claims")
    policy = relationship("Policy", back_populates="claims")
    explanation_record = relationship("ClaimExplanation", back_populates="claim", uselist=False, cascade="all, delete-orphan")
    fraud_check = relationship("FraudCheck", back_populates="claim", uselist=False, cascade="all, delete-orphan")
    fraud_flags = relationship("FraudFlag", back_populates="claim", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────
# 6. CLAIM EXPLANATIONS
# ─────────────────────────────────────────────────────────────────

class ClaimExplanation(Base):
    __tablename__ = "claim_explanations"

    id = Column(String, primary_key=True, default=gen_uuid)
    claim_id = Column(String, ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)

    explanation = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    # Relationships
    claim = relationship("Claim", back_populates="explanation_record")


# ─────────────────────────────────────────────────────────────────
# 7. FRAUD CHECKS
# ─────────────────────────────────────────────────────────────────

class FraudCheck(Base):
    __tablename__ = "fraud_checks"

    id = Column(String, primary_key=True, default=gen_uuid)
    claim_id = Column(String, ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)

    gps_valid = Column(Boolean, nullable=True)
    gps_distance_km = Column(Float, nullable=True)

    multi_server_ok = Column(Boolean, nullable=True)

    score_variance_flag = Column(Boolean, nullable=True)
    anomaly_flag = Column(Boolean, nullable=True)

    fraud_score = Column(Float, nullable=True)
    verdict = Column(Text, nullable=True)       # clean / suspicious / fraudulent

    created_at = Column(DateTime, default=utcnow)

    # Relationships
    claim = relationship("Claim", back_populates="fraud_check")


# ─────────────────────────────────────────────────────────────────
# 8. FRAUD FLAGS
# ─────────────────────────────────────────────────────────────────

class FraudFlag(Base):
    __tablename__ = "fraud_flags"

    id = Column(String, primary_key=True, default=gen_uuid)
    claim_id = Column(String, ForeignKey("claims.id", ondelete="CASCADE"), nullable=True)

    flag_type = Column(Text, nullable=True)
    severity = Column(Float, nullable=True)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    # Relationships
    claim = relationship("Claim", back_populates="fraud_flags")


# ─────────────────────────────────────────────────────────────────
# 9. RISK SIGNALS
# ─────────────────────────────────────────────────────────────────

class RiskSignal(Base):
    __tablename__ = "risk_signals"

    id = Column(String, primary_key=True, default=gen_uuid)

    worker_id = Column(String, ForeignKey("workers.id", ondelete="CASCADE"), nullable=True)
    zone = Column(Text, nullable=True)

    weather_score = Column(Float, nullable=True)
    traffic_score = Column(Float, nullable=True)
    social_score = Column(Float, nullable=True)

    weather_level = Column(Text, nullable=True)
    traffic_level = Column(Text, nullable=True)
    social_level = Column(Text, nullable=True)

    source_weather = Column(Text, nullable=True)
    source_traffic = Column(Text, nullable=True)
    source_social = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    # Relationships
    worker = relationship("Worker", back_populates="risk_signals")


# ─────────────────────────────────────────────────────────────────
# 10. NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_uuid)

    user_id = Column(String, ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=True)

    # Column named "type" in SQL, mapped as notification_type in Python
    notification_type = Column("type", Text, nullable=True)
    title = Column(Text, nullable=True)
    message = Column(Text, nullable=True)

    is_read = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)

    # Relationships
    user = relationship("AuthUser", back_populates="notifications")
