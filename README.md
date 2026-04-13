# 🌧️ Drizzle — Parametric Insurance for Gig Workers

> Intelligent insurance platform that monitors real-world disruptions, automatically processes claims, and provides instant payouts to gig economy workers.

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-blue.svg)](https://supabase.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Database Schema](#-database-schema)
- [API Endpoints](#-api-endpoints)
- [MCP System](#-mcp-system-model-context-protocol)
- [Scoring & Payout Logic](#-scoring--payout-logic)
- [Setup & Installation](#-setup--installation)
- [Deployment](#-deployment-render)
- [Environment Variables](#-environment-variables)

---

## 🧠 Overview

Drizzle is a **parametric insurance platform** designed specifically for gig economy workers (delivery riders, cab drivers, etc.). Unlike traditional insurance that requires manual claim filing and lengthy verification, Drizzle:

1. **Monitors real-world disruptions** in real-time (weather, traffic, social unrest)
2. **Automatically decides** if a worker should get paid using AI reasoning
3. **Calculates payout instantly** using transparent, formula-based logic
4. **Stores everything** in a PostgreSQL database for audit trails

### How It Works

```
Worker triggers claim → 3 MCP servers queried in parallel
                          ├── Weather (rain, AQI, temp, floods)
                          ├── Traffic (congestion, road closures)
                          └── Social (protests, bandhs, strikes)
                        ↓
                    Scores fused → LLM reasoning (GPT-4o-mini)
                        ↓
                    Decision: trigger/reject + payout calculation
                        ↓
                    Saved to DB + notification sent
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                    │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │   Auth   │  │ Workers  │  │ Policies │  │ Claims  │ │
│  │  Router  │  │  Router  │  │  Router  │  │ Router  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│       │              │              │              │      │
│  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐  ┌────┴────┐ │
│  │   Auth   │  │          │  │  Policy  │  │  Claim  │ │
│  │ Service  │  │          │  │ Service  │  │ Service │ │
│  └──────────┘  │          │  └──────────┘  └────┬────┘ │
│                │          │                      │      │
│  ┌─────────┐   │          │   ┌──────────────────┴───┐  │
│  │  Risk   │   │          │   │    Risk Service      │  │
│  │ Router  ├───┤          │   │  (MCP Client Inside) │  │
│  └─────────┘   │          │   └───┬──────┬──────┬────┘  │
│                │          │       │      │      │       │
│  ┌───────────┐ │          │   ┌───┴──┐┌──┴──┐┌──┴───┐  │
│  │  Notif.  │ │          │   │ 🌧️  ││ 🚗 ││ 📢  │  │
│  │  Router  │ │          │   │ MCP  ││ MCP ││ MCP  │  │
│  └──────────┘ │          │   │ 8001 ││ 8002││ 8003 │  │
│               │          │   └──────┘└─────┘└──────┘  │
│               │          │                             │
│  ┌────────────┴──────────┴─────────────────────────┐   │
│  │           PostgreSQL (Supabase)                  │   │
│  │  auth_users │ workers │ policies │ claims │ ...  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### Worker Portal (Fully Implemented)

| Feature | Description |
|---------|-------------|
| 🔐 **Authentication** | Email + password signup/login with JWT tokens |
| 👤 **Worker Profile** | Create/update profile with zone, platform, vehicle info |
| 📋 **Policy Management** | Calculate premiums, create/view policies |
| ⚡ **Live Risk Assessment** | Real-time risk scores from 3 MCP servers |
| 🎯 **Claim Triggering** | Automated claim processing with AI reasoning |
| 🔔 **Notifications** | Auto-generated notifications for payouts and alerts |
| 🛡️ **Fraud Detection** | Basic fraud checks (rapid claim frequency) |

### MCP Integration

| Server | Data Source | Score |
|--------|------------|-------|
| 🌧️ **Weather** | WeatherAPI, OpenWeatherMap, OpenAQ | Rain + AQI + Temperature |
| 🚗 **Traffic** | TomTom Flow API | Congestion + Travel Time + Road Closure |
| 📢 **Social** | Reddit RSS, NewsAPI | Keyword-weighted protest/disruption signals |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Framework** | FastAPI (Python 3.9+) |
| **Database** | PostgreSQL via Supabase |
| **ORM** | SQLAlchemy 2.0 (async) |
| **DB Driver** | asyncpg |
| **Auth** | Custom JWT (PyJWT) |
| **AI Reasoning** | OpenAI GPT-4o-mini |
| **HTTP Client** | httpx (async) |
| **Validation** | Pydantic v2 |
| **Deployment** | Render (uvicorn) |

---

## 📁 Project Structure

```
Guidewire_Drizzle1/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Settings (env vars)
│   │   ├── database.py         # Async SQLAlchemy engine
│   │   └── security.py         # JWT auth middleware
│   ├── models/
│   │   ├── __init__.py
│   │   └── models.py           # All 10 ORM models
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── schemas.py          # Pydantic request/response
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py             # /auth/*
│   │   ├── workers.py          # /workers/*
│   │   ├── policies.py         # /policies/*
│   │   ├── claims.py           # /claims/*
│   │   ├── risk.py             # /risk/*
│   │   └── notifications.py    # /notifications/*
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py     # Auth business logic
│   │   ├── policy_service.py   # Policy business logic
│   │   ├── claim_service.py    # Claim orchestration
│   │   └── risk_service.py     # MCP client + scoring
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── mcp_client.py       # MCP HTTP client wrapper
│   └── utils/
│       └── __init__.py
├── weather_server.py           # MCP Weather Server (port 8001)
├── traffic_server.py           # MCP Traffic Server (port 8002)
├── social_server.py            # MCP Social Server (port 8003)
├── mcp_client.py               # Standalone MCP Client (reference)
├── requirements.txt
├── Procfile                    # Render deployment
├── render.yaml                 # Render config
├── .env                        # Environment variables
├── .env.example                # Env template
├── .gitignore
└── README.md
```

---

## 🗄️ Database Schema

### 10 Tables

| Table | Description |
|-------|-------------|
| `auth_users` | User accounts (email, password, role) |
| `auth_sessions` | JWT session tracking |
| `workers` | Worker profiles (zone, platform, vehicle) |
| `policies` | Insurance policies (coverage, premium, status) |
| `claims` | Claim records with scores, payout, explanation |
| `claim_explanations` | LLM reasoning snapshots |
| `fraud_checks` | Fraud detection results per claim |
| `fraud_flags` | Persistent fraud flags per worker |
| `risk_signals` | Historical risk signal storage |
| `notifications` | User notifications (payout alerts, etc.) |

### Key Relationships

```
auth_users ──1:1──> workers ──1:N──> policies ──1:N──> claims
     │                                                    │
     │                                              ┌─────┤
     └──1:N──> notifications                   claim_explanations
                                                fraud_checks
```

---

## 📡 API Endpoints

### Authentication

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/auth/signup` | Create account | ❌ |
| `POST` | `/auth/login` | Login → JWT token | ❌ |
| `GET` | `/auth/me` | Get current user | ✅ |

### Workers

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/workers/profile` | Create/update profile | ✅ |
| `GET` | `/workers/me` | Get my profile | ✅ |

### Policies

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/policies/calculate` | Calculate premium | ✅ |
| `POST` | `/policies/create` | Create new policy | ✅ |
| `GET` | `/policies/my` | List my policies | ✅ |
| `GET` | `/policies/{id}` | Get policy detail | ✅ |

### Claims

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/claims/trigger` | Trigger claim (full MCP pipeline) | ✅ |
| `GET` | `/claims/my` | List my claims | ✅ |
| `GET` | `/claims/{id}` | Get claim detail | ✅ |

### Risk

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/risk/live` | Live risk from 3 MCP servers | ✅ |

### Notifications

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/notifications` | List all notifications | ✅ |
| `POST` | `/notifications/read/{id}` | Mark as read | ✅ |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API info + endpoint list |
| `GET` | `/health` | Health check (DB + MCP servers) |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |

---

## ⚡ MCP System (Model Context Protocol)

### Three Independent Servers

#### 1. Weather MCP Server (Port 8001)
- **Sources**: WeatherAPI.com (primary), OpenWeatherMap (fallback), OpenAQ (AQI)
- **Scoring Formula**: `0.50 × rain_score + 0.30 × aqi_score + 0.20 × temp_score`
- **Rain scoring**: IMD intensity bands (7/15/30/50 mm/hr → 0.25/0.50/0.80/0.95)
- **AQI scoring**: US EPA bands (50/100/150/200/300 → 0.00/0.20/0.40/0.60/0.85)

#### 2. Traffic MCP Server (Port 8002)
- **Source**: TomTom Flow Segment API
- **Scoring Formula**: `0.60 × congestion_score + 0.30 × travel_time_score + road_penalty`
- **Congestion**: `1 - (current_speed / free_flow_speed)` clamped 0-1
- **Road closure**: +0.30 fixed penalty

#### 3. Social MCP Server (Port 8003)
- **Sources**: Reddit public JSON API (no key), NewsAPI
- **Keywords**: bandh(1.0), shutdown(1.0), curfew(1.0), protest(0.7), rally(0.6), strike(0.6), roadblock(0.5), blockade(0.5), waterlog(0.4), flood(0.4), jam(0.3)
- **Scoring**: Top 5 weighted keyword hits, normalized to 5.0 max

---

## 🧮 Scoring & Payout Logic

### Fused Score
```
disruption_intensity = 0.35 × weather + 0.25 × traffic + 0.25 × social
```

### Claim Trigger Rules
```
HIGH in any single server    → TRIGGER
MEDIUM in 2+ servers         → TRIGGER
Otherwise                    → NO TRIGGER
```

### Confidence Levels
```
Score ≥ 0.60  → HIGH
Score ≥ 0.30  → MEDIUM
Score < 0.30  → LOW
```

### Payout Calculation
```
base_income       = zone-based daily income (₹850–₹1400)
income_loss_ratio = disruption_intensity × confidence_multiplier
income_loss       = base_income × income_loss_ratio
payout            = income_loss × 0.80  (80% coverage)
```

| Confidence | Multiplier |
|-----------|-----------|
| HIGH | 1.00 |
| MEDIUM | 0.75 |
| LOW | 0.50 |

### Zone Base Income (INR/day)

| Zone | Daily Income |
|------|-------------|
| Mumbai | ₹1,400 |
| Delhi | ₹1,300 |
| Bangalore | ₹1,250 |
| Hyderabad | ₹1,100 |
| Noida | ₹1,100 |
| Chennai | ₹1,000 |
| Pune | ₹1,050 |
| Kolkata | ₹950 |
| Jaipur | ₹850 |
| Default | ₹1,000 |

---

## 🚀 Setup & Installation

### Prerequisites

- Python 3.9+
- PostgreSQL (Supabase account)
- API Keys: WeatherAPI, TomTom, NewsAPI, OpenAI

### 1. Clone & Install

```bash
git clone <repository-url>
cd Guidewire_Drizzle1

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual values (especially DATABASE_URL)
```

### 3. Start MCP Servers

```bash
# Terminal 1 — Weather
uvicorn weather_server:app --port 8001 --reload

# Terminal 2 — Traffic
uvicorn traffic_server:app --port 8002 --reload

# Terminal 3 — Social
uvicorn social_server:app --port 8003 --reload
```

### 4. Start Main API

```bash
# Terminal 4 — Main Backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Test

```bash
# Health check
curl http://localhost:8000/health

# Docs
open http://localhost:8000/docs
```

---

## 🌐 Deployment (Render)

### Single Service

```bash
# Build command
pip install -r requirements.txt

# Start command
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### render.yaml

The `render.yaml` file is included for one-click deployment. Set the following environment variables in Render dashboard:

- `DATABASE_URL` — Supabase PostgreSQL connection string
- `JWT_SECRET_KEY` — Auto-generated
- `OPENAI_API_KEY`, `WEATHERAPI_KEY`, `TOMTOM_API_KEY`, `NEWSAPI_KEY`
- `WEATHER_MCP_URL`, `TRAFFIC_MCP_URL`, `SOCIAL_MCP_URL`

---

## ⚙️ Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL async connection string | ✅ |
| `JWT_SECRET_KEY` | Secret for JWT signing | ✅ |
| `OPENAI_API_KEY` | OpenAI API key (GPT-4o-mini) | ⚠️ Fallback available |
| `WEATHERAPI_KEY` | WeatherAPI.com key | ✅ |
| `TOMTOM_API_KEY` | TomTom Traffic API key | ✅ |
| `NEWSAPI_KEY` | NewsAPI key | ✅ |
| `WEATHER_MCP_URL` | Weather MCP server URL | ✅ |
| `TRAFFIC_MCP_URL` | Traffic MCP server URL | ✅ |
| `SOCIAL_MCP_URL` | Social MCP server URL | ✅ |
| `PORT` | Server port (default: 8000) | ❌ |
| `DEBUG` | Enable debug logging | ❌ |

---

## 📝 API Flow Examples

### Complete Worker Journey

```bash
# 1. Sign up
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"rider@test.com","password":"pass123","full_name":"Test Rider"}'

# 2. Create worker profile (use token from step 1)
curl -X POST http://localhost:8000/workers/profile \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Test Rider","phone":"9876543210","gig_platform":"Swiggy","vehicle_type":"bike","zone":"OMR-Chennai","city":"Chennai","latitude":13.0827,"longitude":80.2707}'

# 3. Calculate premium
curl -X POST http://localhost:8000/policies/calculate \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"zone":"OMR-Chennai","vehicle_type":"bike","avg_daily_income":1000}'

# 4. Create policy
curl -X POST http://localhost:8000/policies/create \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"coverage_amount":800,"premium_amount":360,"zone":"OMR-Chennai"}'

# 5. Check live risk
curl "http://localhost:8000/risk/live?lat=13.0827&lon=80.2707&zone=OMR-Chennai" \
  -H "Authorization: Bearer <TOKEN>"

# 6. Trigger claim
curl -X POST http://localhost:8000/claims/trigger \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"latitude":13.0827,"longitude":80.2707,"zone":"OMR-Chennai"}'

# 7. Check notifications
curl http://localhost:8000/notifications \
  -H "Authorization: Bearer <TOKEN>"
```

---

## 🏗️ What's Built

- [x] Full async FastAPI application
- [x] 10 database tables (SQLAlchemy ORM)
- [x] JWT authentication (signup, login, middleware)
- [x] Worker profile management
- [x] Policy calculation & creation
- [x] Live risk assessment (3 MCP servers)
- [x] Automated claim triggering with AI reasoning
- [x] Formula-based payout calculation
- [x] Basic fraud detection
- [x] Notification system
- [x] Health check endpoint
- [x] Render deployment configuration
- [x] Comprehensive API documentation (Swagger)

---

## 📄 License

MIT License — Built for the Guidewire Hackathon.
