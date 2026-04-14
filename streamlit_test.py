"""
╔══════════════════════════════════════════════════════════════════╗
║         DRIZZLE — Interactive Testing Dashboard                 ║
║      Worker Portal + Admin Portal (Streamlit)                   ║
╚══════════════════════════════════════════════════════════════════╝

Run:
    streamlit run streamlit_test.py

Prereq: All 4 servers running on ports 8000–8003
"""

import json
import sqlite3
import streamlit as st
import requests

BASE = "http://127.0.0.1:8000"
DB_PATH = "drizzle_local.db"


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def api(method, path, token=None, data=None, params=None):
    """Make API call and return (status_code, json_data)."""
    url = f"{BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=data, timeout=30)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=data, timeout=30)
        else:
            return 0, {"error": f"Unknown method {method}"}
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text}
    except requests.ConnectionError:
        return 0, {"error": "Cannot connect to server. Is it running?"}
    except requests.Timeout:
        return 0, {"error": "Request timed out (30s)"}


def show_response(status, data, success_code=200):
    """Display API response with colored status."""
    if status == success_code:
        st.success(f"✅ Status: {status}")
    elif status == 0:
        st.error(f"❌ Connection Error")
    else:
        st.error(f"❌ Status: {status}")
    st.json(data)


def promote_to_admin(user_id):
    """Promote user to admin role in SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE auth_users SET role='admin' WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"DB error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Drizzle — Test Dashboard",
    page_icon="🌧️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); }
    [data-testid="stSidebar"] .stMarkdown h1, [data-testid="stSidebar"] .stMarkdown h2,
    [data-testid="stSidebar"] .stMarkdown h3, [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] .stMarkdown li { color: #e0e0e0 !important; }
    .step-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 12px;
        padding: 20px;
        margin: 10px 0;
    }
    .metric-card {
        background: linear-gradient(135deg, rgba(102,126,234,0.2), rgba(118,75,162,0.2));
        border: 1px solid rgba(102,126,234,0.3);
        border-radius: 12px;
        padding: 20px;
        margin: 5px;
        text-align: center;
    }
    .metric-value { font-size: 2em; font-weight: bold; color: #667eea; }
    .metric-label { font-size: 0.85em; color: #a0a0b0; }
    .guide-box {
        background: rgba(255,193,7,0.08);
        border-left: 4px solid #ffc107;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
        font-size: 0.9em;
    }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════

if "worker_token" not in st.session_state:
    st.session_state.worker_token = None
if "worker_user_id" not in st.session_state:
    st.session_state.worker_user_id = None
if "worker_email" not in st.session_state:
    st.session_state.worker_email = None
if "admin_token" not in st.session_state:
    st.session_state.admin_token = None
if "admin_user_id" not in st.session_state:
    st.session_state.admin_user_id = None
if "admin_email" not in st.session_state:
    st.session_state.admin_email = None
if "claim_id" not in st.session_state:
    st.session_state.claim_id = None
if "policy_id" not in st.session_state:
    st.session_state.policy_id = None


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("# 🌧️ Drizzle")
    st.markdown("**Parametric Insurance for Gig Workers**")
    st.markdown("---")

    # Health check
    try:
        r = requests.get(f"{BASE}/health", timeout=3)
        health = r.json()
        db_ok = health.get("database") == "connected"
        mcp = health.get("mcp_servers", {})
        st.markdown(f"**System Status:**")
        st.markdown(f"- DB: {'🟢' if db_ok else '🔴'} {health.get('database','?')}")
        for name, status in mcp.items():
            st.markdown(f"- MCP {name}: {'🟢' if status=='ok' else '🔴'} {status}")
        st.markdown(f"- OpenAI: {'🟢' if health.get('openai_configured') else '🔴'}")
    except Exception:
        st.error("❌ Server offline")

    st.markdown("---")

    # Portal selector
    portal = st.radio(
        "Select Portal",
        ["👷 Worker Portal", "🛡️ Admin Portal", "🗃️ Database"],
        index=0,
    )

    st.markdown("---")

    # Show auth state
    st.markdown("**Active Sessions:**")
    if st.session_state.worker_token:
        st.markdown(f"- 👷 `{st.session_state.worker_email}`")
    else:
        st.markdown("- 👷 Not logged in")
    if st.session_state.admin_token:
        st.markdown(f"- 🛡️ `{st.session_state.admin_email}`")
    else:
        st.markdown("- 🛡️ Not logged in")


# ═══════════════════════════════════════════════════════════════════
# WORKER PORTAL
# ═══════════════════════════════════════════════════════════════════

if portal == "👷 Worker Portal":
    st.markdown("# 👷 Worker Portal")
    st.markdown("*Complete flow: Signup → Login → Profile → Premium → Policy → Claim → Risk → Notifications*")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "1️⃣ Auth", "2️⃣ Profile", "3️⃣ Premium", "4️⃣ Policy",
        "5️⃣ Claim", "6️⃣ Risk", "7️⃣ History", "8️⃣ Notifications",
    ])

    # ── TAB 1: AUTH ───────────────────────────────────────────────
    with tab1:
        st.markdown("### 🔐 Authentication")
        st.markdown('<div class="guide-box">💡 <b>How it works:</b> Creates a row in <code>auth_users</code> table. Password stored as plain text (dev mode). JWT token generated with user_id, email, role encoded inside.</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Signup")
            signup_email = st.text_input("Email", value="rider@swiggy.in", key="s_email")
            signup_password = st.text_input("Password", value="rider2024", type="password", key="s_pass")
            signup_phone = st.text_input("Phone", value="+919876500001", key="s_phone")

            if st.button("🚀 Sign Up", key="btn_signup", use_container_width=True):
                status, data = api("POST", "/auth/signup", data={
                    "email": signup_email,
                    "password": signup_password,
                    "phone": signup_phone,
                })
                show_response(status, data, 201)
                if status == 201:
                    st.session_state.worker_token = data.get("token")
                    st.session_state.worker_user_id = data.get("user_id")
                    st.session_state.worker_email = data.get("email")
                    st.success("🎉 Token saved! Proceed to Profile tab.")

        with col2:
            st.markdown("#### Login")
            login_email = st.text_input("Email", value="rider@swiggy.in", key="l_email")
            login_password = st.text_input("Password", value="rider2024", type="password", key="l_pass")

            if st.button("🔑 Log In", key="btn_login", use_container_width=True):
                status, data = api("POST", "/auth/login", data={
                    "email": login_email,
                    "password": login_password,
                })
                show_response(status, data)
                if status == 200:
                    st.session_state.worker_token = data.get("token")
                    st.session_state.worker_user_id = data.get("user_id")
                    st.session_state.worker_email = data.get("email")
                    st.success("🎉 Logged in! Token refreshed.")

        st.markdown("---")
        st.markdown("#### 👤 My Profile")
        st.markdown('<div class="guide-box">💡 Decodes your JWT token and fetches your user profile from <code>auth_users</code> table.</div>', unsafe_allow_html=True)
        if st.button("📋 Get My Auth Profile", key="btn_me"):
            if not st.session_state.worker_token:
                st.warning("⚠️ Login first!")
            else:
                status, data = api("GET", "/auth/me", token=st.session_state.worker_token)
                show_response(status, data)

    # ── TAB 2: WORKER PROFILE ────────────────────────────────────
    with tab2:
        st.markdown("### 👤 Worker Profile")
        st.markdown('<div class="guide-box">💡 <b>How it works:</b> Creates a row in <code>workers</code> table with shared PK from <code>auth_users</code>. Zone determines risk multiplier for premium. GPS used for fraud check validation.</div>', unsafe_allow_html=True)

        if not st.session_state.worker_token:
            st.warning("⚠️ Sign up or log in first (Auth tab)")
        else:
            col1, col2 = st.columns(2)
            with col1:
                full_name = st.text_input("Full Name", value="Vikram Singh")
                phone = st.text_input("Phone", value="+919876500001", key="wp_phone")
                zone = st.selectbox("Zone", [
                    "Connaught-Place-Delhi", "Andheri-Mumbai", "Koramangala-Bangalore",
                    "T-Nagar-Chennai", "Gachibowli-Hyderabad", "Salt-Lake-Kolkata",
                    "Sector-62-Noida", "Hinjewadi-Pune", "Vaishali-Nagar-Jaipur",
                ])
                vehicle = st.selectbox("Vehicle Type", ["bike", "scooter", "cycle", "car"])

            with col2:
                gps_lat = st.number_input("GPS Latitude", value=28.6315, format="%.4f")
                gps_lon = st.number_input("GPS Longitude", value=77.2167, format="%.4f")
                income = st.number_input("Daily Income (₹)", value=1400, min_value=100, step=100)

            if st.button("💾 Create / Update Profile", key="btn_profile", use_container_width=True):
                status, data = api("POST", "/workers/profile", token=st.session_state.worker_token, data={
                    "full_name": full_name, "phone": phone, "zone": zone,
                    "vehicle_type": vehicle, "gps_lat": gps_lat, "gps_lon": gps_lon,
                    "daily_income_estimate": income,
                })
                show_response(status, data, 201)

            st.markdown("---")
            if st.button("📋 Get My Worker Profile", key="btn_get_profile"):
                status, data = api("GET", "/workers/me", token=st.session_state.worker_token)
                show_response(status, data)

    # ── TAB 3: PREMIUM CALCULATOR ────────────────────────────────
    with tab3:
        st.markdown("### 💰 Premium Calculator")
        st.markdown('<div class="guide-box">💡 <b>How it works:</b> <code>sum_insured = income × 0.8</code>, <code>premium = sum × zone_mult × vehicle_mult × days × rate</code>. High-risk zones (Mumbai 1.3×, Delhi 1.25×) cost more. Bikes (1.2×) cost more than cars (1.0×). This is a read-only estimate — no policy created yet.</div>', unsafe_allow_html=True)

        if not st.session_state.worker_token:
            st.warning("⚠️ Login first")
        else:
            col1, col2 = st.columns(2)
            with col1:
                calc_zone = st.selectbox("Zone", [
                    "Connaught-Place-Delhi", "Andheri-Mumbai", "Koramangala-Bangalore",
                    "T-Nagar-Chennai", "Gachibowli-Hyderabad",
                ], key="calc_zone")
                calc_vehicle = st.selectbox("Vehicle", ["bike", "scooter", "cycle", "car"], key="calc_veh")
            with col2:
                calc_income = st.number_input("Daily Income (₹)", value=1400, min_value=100, step=100, key="calc_income")
                calc_coverage = st.selectbox("Coverage Type", ["standard", "premium"], key="calc_cov")

            if st.button("📊 Calculate Premium", key="btn_calc", use_container_width=True):
                status, data = api("POST", "/policies/calculate", token=st.session_state.worker_token, data={
                    "zone": calc_zone, "vehicle_type": calc_vehicle,
                    "daily_income_estimate": calc_income, "coverage_type": calc_coverage,
                })
                show_response(status, data)
                if status == 200:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Sum Insured", f"₹{data.get('sum_insured', 0)}")
                    c2.metric("Monthly Premium", f"₹{data.get('premium', 0)}")
                    c3.metric("Zone Multiplier", f"{data.get('zone_multiplier', 0)}×")

    # ── TAB 4: POLICY ────────────────────────────────────────────
    with tab4:
        st.markdown("### 📋 Policy Management")
        st.markdown('<div class="guide-box">💡 <b>How it works:</b> Creates a row in <code>policies</code> table with status=active, start_date=now, end_date=now+coverage_days. Only ONE active policy per worker. Blocks if existing active policy found.</div>', unsafe_allow_html=True)

        if not st.session_state.worker_token:
            st.warning("⚠️ Login first")
        else:
            col1, col2 = st.columns(2)
            with col1:
                pol_coverage = st.selectbox("Coverage", ["standard", "premium"], key="pol_cov")
                pol_days = st.number_input("Coverage Days", value=30, min_value=1, key="pol_days")
                pol_sum = st.number_input("Sum Insured (₹)", value=1120.0, min_value=1.0, key="pol_sum")
            with col2:
                pol_premium = st.number_input("Premium (₹)", value=1512.0, min_value=1.0, key="pol_prem")
                pol_zone_mult = st.number_input("Zone Multiplier", value=1.25, min_value=0.0, key="pol_zm")

            if st.button("🛡️ Create Policy", key="btn_create_pol", use_container_width=True):
                status, data = api("POST", "/policies/create", token=st.session_state.worker_token, data={
                    "coverage_type": pol_coverage, "coverage_days": pol_days,
                    "sum_insured": pol_sum, "premium": pol_premium, "zone_multiplier": pol_zone_mult,
                })
                show_response(status, data, 201)
                if status == 201:
                    st.session_state.policy_id = data.get("id")

            st.markdown("---")
            if st.button("📋 View My Policies", key="btn_my_pol"):
                status, data = api("GET", "/policies/my", token=st.session_state.worker_token)
                show_response(status, data)

    # ── TAB 5: CLAIM TRIGGER ─────────────────────────────────────
    with tab5:
        st.markdown("### 🔥 Trigger Claim")
        st.markdown('<div class="guide-box">💡 <b>The CORE feature!</b> This calls 3 MCP servers in parallel:<br>🌦️ <b>Weather</b> → WeatherAPI.com (rain, temp, AQI, flood risk)<br>🚗 <b>Traffic</b> → TomTom API (congestion, speed ratio, incidents)<br>📰 <b>Social</b> → Reddit + NewsAPI (protests, strikes, bandhs)<br><br>Fused score = 0.4×Weather + 0.35×Traffic + 0.25×Social<br>GPT-4o-mini analyzes all data → decide claim + payout<br>Fraud check runs → notification created → saved to DB</div>', unsafe_allow_html=True)

        if not st.session_state.worker_token:
            st.warning("⚠️ Login first")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                claim_lat = st.number_input("Latitude", value=28.6315, format="%.4f", key="claim_lat")
            with col2:
                claim_lon = st.number_input("Longitude", value=77.2167, format="%.4f", key="claim_lon")
            with col3:
                claim_zone = st.text_input("Zone", value="Connaught-Place-Delhi", key="claim_zone")

            st.markdown("**Quick Location Presets:**")
            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                if st.button("📍 Delhi", key="preset_del"):
                    st.session_state["claim_lat"] = 28.6315
                    st.session_state["claim_lon"] = 77.2167
                    st.rerun()
            with pc2:
                if st.button("📍 Mumbai", key="preset_mum"):
                    st.session_state["claim_lat"] = 19.076
                    st.session_state["claim_lon"] = 72.8777
                    st.rerun()
            with pc3:
                if st.button("📍 Bangalore", key="preset_blr"):
                    st.session_state["claim_lat"] = 12.9716
                    st.session_state["claim_lon"] = 77.5946
                    st.rerun()
            with pc4:
                if st.button("📍 Chennai", key="preset_che"):
                    st.session_state["claim_lat"] = 13.0827
                    st.session_state["claim_lon"] = 80.2707
                    st.rerun()

            if st.button("⚡ TRIGGER CLAIM ASSESSMENT", key="btn_trigger", use_container_width=True, type="primary"):
                with st.spinner("🔄 Calling MCP servers + GPT-4o-mini... (10-15 seconds)"):
                    status, data = api("POST", "/claims/trigger", token=st.session_state.worker_token, data={
                        "lat": claim_lat, "lon": claim_lon, "zone": claim_zone,
                    })
                show_response(status, data)
                if status == 200:
                    st.session_state.claim_id = data.get("id")
                    scores = data.get("scores", {})

                    st.markdown("#### 📊 Risk Scores")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("🌦️ Weather", f"{scores.get('weather_score', 0):.2f}", scores.get("weather_level"))
                    c2.metric("🚗 Traffic", f"{scores.get('traffic_score', 0):.2f}", scores.get("traffic_level"))
                    c3.metric("📰 Social", f"{scores.get('social_score', 0):.2f}", scores.get("social_level"))
                    c4.metric("🔥 Fused", f"{scores.get('fused_score', 0):.2f}")

                    st.markdown("#### 🤖 GPT-4o-mini Decision")
                    st.info(f"**Status:** {data.get('status')} | **Cause:** {data.get('primary_cause')} | **Confidence:** {data.get('confidence')}")
                    st.markdown(f"> {data.get('explanation', '')}")

                    if data.get("payout"):
                        st.markdown("#### 💰 Payout")
                        payout = data["payout"]
                        st.success(f"**₹{payout.get('payout_amount_inr', 0):.0f}** credited!")

                    st.markdown("#### 🔍 Fraud Check")
                    fraud = data.get("fraud_check", {})
                    st.json(fraud)

    # ── TAB 6: LIVE RISK ─────────────────────────────────────────
    with tab6:
        st.markdown("### 📡 Live Risk Assessment")
        st.markdown('<div class="guide-box">💡 <b>Read-only</b> — Same MCP pipeline as claims but no claim created. Use for dashboard monitoring. Shows real-time weather, traffic, social signals at any location.</div>', unsafe_allow_html=True)

        if not st.session_state.worker_token:
            st.warning("⚠️ Login first")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                risk_lat = st.number_input("Latitude", value=19.076, format="%.4f", key="risk_lat")
            with col2:
                risk_lon = st.number_input("Longitude", value=72.8777, format="%.4f", key="risk_lon")
            with col3:
                risk_zone = st.text_input("Zone", value="Bandra-Mumbai", key="risk_zone")

            if st.button("📡 Check Live Risk", key="btn_risk", use_container_width=True, type="primary"):
                with st.spinner("🔄 Querying MCP servers + GPT-4o-mini..."):
                    status, data = api("GET", "/risk/live", token=st.session_state.worker_token,
                                       params={"lat": risk_lat, "lon": risk_lon, "zone": risk_zone})
                show_response(status, data)

    # ── TAB 7: HISTORY ───────────────────────────────────────────
    with tab7:
        st.markdown("### 📜 Claims & Policy History")

        if not st.session_state.worker_token:
            st.warning("⚠️ Login first")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### My Claims")
                if st.button("🔄 Load Claims", key="btn_my_claims"):
                    status, data = api("GET", "/claims/my", token=st.session_state.worker_token)
                    show_response(status, data)

            with col2:
                st.markdown("#### My Policies")
                if st.button("🔄 Load Policies", key="btn_my_pols2"):
                    status, data = api("GET", "/policies/my", token=st.session_state.worker_token)
                    show_response(status, data)

    # ── TAB 8: NOTIFICATIONS ─────────────────────────────────────
    with tab8:
        st.markdown("### 🔔 Notifications")
        st.markdown('<div class="guide-box">💡 Auto-created by the system: claim approved → payout notification, claim rejected → alert. Stored in <code>notifications</code> table linked to user_id.</div>', unsafe_allow_html=True)

        if not st.session_state.worker_token:
            st.warning("⚠️ Login first")
        else:
            if st.button("🔄 Load Notifications", key="btn_load_notifs"):
                status, data = api("GET", "/notifications", token=st.session_state.worker_token)
                show_response(status, data)
                if status == 200:
                    notifs = data.get("notifications", [])
                    for n in notifs:
                        with st.expander(f"{'📩' if not n.get('is_read') else '✉️'} {n.get('title', 'Notification')}"):
                            st.markdown(f"**{n.get('message', '')}**")
                            st.caption(f"Type: {n.get('notification_type')} | Read: {n.get('is_read')} | {n.get('created_at', '')[:19]}")
                            if not n.get("is_read"):
                                if st.button(f"✅ Mark Read", key=f"read_{n['id']}"):
                                    s2, d2 = api("POST", f"/notifications/read/{n['id']}", token=st.session_state.worker_token)
                                    if s2 == 200:
                                        st.success("Marked as read!")
                                        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# ADMIN PORTAL
# ═══════════════════════════════════════════════════════════════════

elif portal == "🛡️ Admin Portal":
    st.markdown("# 🛡️ Admin Portal")
    st.markdown("*Full admin control: Dashboard → Workers → Policies → Claims → Fraud → Config → Analytics → Audit*")

    # Admin auth section
    with st.expander("🔐 Admin Authentication", expanded=not bool(st.session_state.admin_token)):
        st.markdown('<div class="guide-box">💡 Admin accounts are created as workers first, then promoted via DB. The JWT token encodes role=admin, which is checked by <code>require_admin</code> dependency on every admin endpoint.</div>', unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Step 1: Signup**")
            admin_signup_email = st.text_input("Email", value="admin@drizzle.io", key="admin_s_email")
            admin_signup_pass = st.text_input("Password", value="admin2024", type="password", key="admin_s_pass")
            if st.button("📝 Signup", key="btn_admin_signup"):
                status, data = api("POST", "/auth/signup", data={
                    "email": admin_signup_email, "password": admin_signup_pass,
                })
                show_response(status, data, 201)
                if status == 201:
                    st.session_state.admin_user_id = data.get("user_id")

        with col2:
            st.markdown("**Step 2: Promote to Admin**")
            promote_id = st.text_input("User ID", value=st.session_state.admin_user_id or "", key="promote_id")
            if st.button("⬆️ Promote to Admin", key="btn_promote"):
                if promote_id and promote_to_admin(promote_id):
                    st.success("✅ Role set to 'admin' in database!")

        with col3:
            st.markdown("**Step 3: Login (fresh token)**")
            admin_login_email = st.text_input("Email", value="admin@drizzle.io", key="admin_l_email")
            admin_login_pass = st.text_input("Password", value="admin2024", type="password", key="admin_l_pass")
            if st.button("🔑 Admin Login", key="btn_admin_login"):
                status, data = api("POST", "/auth/login", data={
                    "email": admin_login_email, "password": admin_login_pass,
                })
                show_response(status, data)
                if status == 200:
                    st.session_state.admin_token = data.get("token")
                    st.session_state.admin_email = data.get("email")
                    st.session_state.admin_user_id = data.get("user_id")
                    if data.get("role") == "admin":
                        st.success("🎉 Admin token acquired!")
                    else:
                        st.warning("⚠️ Role is still 'worker'. Did you promote?")

    if not st.session_state.admin_token:
        st.info("👆 Complete admin authentication above to unlock features")
    else:
        tab_a1, tab_a2, tab_a3, tab_a4, tab_a5, tab_a6, tab_a7, tab_a8 = st.tabs([
            "📊 Dashboard", "👥 Workers", "📋 Policies", "⚖️ Claims",
            "🚨 Fraud", "⚙️ Config", "📈 Analytics", "📝 Audit",
        ])

        at = st.session_state.admin_token

        # ── DASHBOARD ────────────────────────────────────────────
        with tab_a1:
            st.markdown("### 📊 Admin Dashboard")
            st.markdown('<div class="guide-box">💡 <b>Control Tower</b> — Aggregates data from workers, policies, claims, fraud_alerts, and worker_activity_logs tables. Shows real-time operational metrics.</div>', unsafe_allow_html=True)

            if st.button("🔄 Load Dashboard", key="btn_dash", use_container_width=True):
                status, data = api("GET", "/admin/dashboard", token=at)
                show_response(status, data)
                if status == 200:
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("👷 Workers", data.get("total_workers", 0))
                    c2.metric("📋 Active Policies", data.get("active_policies", 0))
                    c3.metric("📝 Claims Today", data.get("claims_today", 0))
                    c4.metric("💰 Payout Today", f"₹{data.get('total_payout_today', 0):.0f}")
                    c5.metric("🚨 Fraud Alerts", data.get("fraud_alerts_count", 0))

                    st.markdown("#### Recent Activity")
                    for a in data.get("recent_activity", []):
                        st.markdown(f"- **{a['action']}** by `{a['worker_id'][:8]}...` at {(a.get('created_at') or '')[:19]}")

        # ── WORKERS ──────────────────────────────────────────────
        with tab_a2:
            st.markdown("### 👥 Worker Management")
            st.markdown('<div class="guide-box">💡 View all registered workers and drill into individual profiles with their complete policy and claims history.</div>', unsafe_allow_html=True)

            if st.button("🔄 Load All Workers", key="btn_workers"):
                status, data = api("GET", "/admin/workers", token=at)
                show_response(status, data)

            st.markdown("---")
            st.markdown("#### Worker Detail Lookup")
            worker_lookup_id = st.text_input("Worker ID", value=st.session_state.worker_user_id or "", key="worker_lookup")
            if st.button("🔍 Get Worker Detail", key="btn_worker_detail"):
                status, data = api("GET", f"/admin/workers/{worker_lookup_id}", token=at)
                show_response(status, data)

        # ── POLICIES ─────────────────────────────────────────────
        with tab_a3:
            st.markdown("### 📋 Policy Management")
            st.markdown('<div class="guide-box">💡 List all policies across all workers. Admin can also manually create a policy for a worker (useful for customer support overrides).</div>', unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                pol_status_filter = st.selectbox("Filter by Status", ["(all)", "active", "expired", "cancelled"], key="pol_filter")
            with col2:
                pol_zone_filter = st.text_input("Filter by Zone", value="", key="pol_zone_filter")

            if st.button("🔄 Load All Policies", key="btn_all_pol"):
                params = {}
                if pol_status_filter != "(all)":
                    params["status"] = pol_status_filter
                if pol_zone_filter:
                    params["zone"] = pol_zone_filter
                status, data = api("GET", "/admin/policies", token=at, params=params)
                show_response(status, data)

            st.markdown("---")
            st.markdown("#### Admin Create Policy")
            acol1, acol2 = st.columns(2)
            with acol1:
                ap_worker_id = st.text_input("Worker ID", value=st.session_state.worker_user_id or "", key="ap_wid")
                ap_coverage = st.selectbox("Coverage", ["standard", "premium"], key="ap_cov")
                ap_days = st.number_input("Days", value=30, key="ap_days")
            with acol2:
                ap_sum = st.number_input("Sum Insured", value=1500.0, key="ap_sum")
                ap_prem = st.number_input("Premium", value=2000.0, key="ap_prem")
                ap_zm = st.number_input("Zone Mult", value=1.25, key="ap_zm")

            if st.button("➕ Create Policy for Worker", key="btn_admin_create_pol"):
                status, data = api("POST", "/admin/policies/create", token=at, data={
                    "worker_id": ap_worker_id, "coverage_type": ap_coverage,
                    "coverage_days": ap_days, "sum_insured": ap_sum,
                    "premium": ap_prem, "zone_multiplier": ap_zm,
                })
                show_response(status, data, 201)

        # ── CLAIMS ───────────────────────────────────────────────
        with tab_a4:
            st.markdown("### ⚖️ Claims Management")
            st.markdown('<div class="guide-box">💡 View all claims across all workers with fraud scores. Drill into any claim to see the full breakdown including AI reasoning, fraud check details, and review history. Admin can approve/reject claims with notes — all actions are audit-logged.</div>', unsafe_allow_html=True)

            if st.button("🔄 Load All Claims", key="btn_all_claims"):
                status, data = api("GET", "/admin/claims", token=at)
                show_response(status, data)

            st.markdown("---")
            st.markdown("#### Claim Detail")
            claim_lookup = st.text_input("Claim ID", value=st.session_state.claim_id or "", key="claim_lookup")
            if st.button("🔍 Get Claim Detail", key="btn_claim_detail"):
                status, data = api("GET", f"/admin/claims/{claim_lookup}", token=at)
                show_response(status, data)

            st.markdown("---")
            st.markdown("#### ⚖️ Review Claim")
            st.markdown('<div class="guide-box">💡 <b>Flow:</b> Insert into <code>claim_reviews</code> → update <code>claims.status</code> → write <code>audit_logs</code>. The worker will see the updated status instantly.</div>', unsafe_allow_html=True)

            review_claim_id = st.text_input("Claim ID to Review", value=st.session_state.claim_id or "", key="review_cid")
            review_decision = st.selectbox("Decision", ["approve", "reject"], key="review_dec")
            review_notes = st.text_area("Notes", value="Verified via field report", key="review_notes")

            if st.button("📝 Submit Review", key="btn_review", type="primary"):
                status, data = api("POST", f"/admin/claims/{review_claim_id}/review", token=at, data={
                    "decision": review_decision, "notes": review_notes,
                })
                show_response(status, data)

        # ── FRAUD ────────────────────────────────────────────────
        with tab_a5:
            st.markdown("### 🚨 Fraud Detection & Risk")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Fraud Alerts")
                st.markdown('<div class="guide-box">💡 Auto-created when a claim\'s fraud_check verdict is "suspicious" or "fraudulent" (rapid claims in 24hrs). Admin can resolve alerts after investigation.</div>', unsafe_allow_html=True)

                fraud_filter = st.selectbox("Filter", ["(all)", "Unresolved", "Resolved"], key="fraud_f")
                if st.button("🔄 Load Fraud Alerts", key="btn_fraud"):
                    params = {}
                    if fraud_filter == "Unresolved":
                        params["resolved"] = "false"
                    elif fraud_filter == "Resolved":
                        params["resolved"] = "true"
                    status, data = api("GET", "/admin/fraud-alerts", token=at, params=params)
                    show_response(status, data)

                st.markdown("---")
                resolve_id = st.text_input("Alert ID to Resolve", key="resolve_id")
                if st.button("✅ Resolve Alert", key="btn_resolve"):
                    status, data = api("POST", f"/admin/fraud-alerts/{resolve_id}/resolve", token=at)
                    show_response(status, data)

            with col2:
                st.markdown("#### Zone-Level Risk")
                st.markdown('<div class="guide-box">💡 Aggregated from <code>risk_signals</code> table — shows avg weather/traffic/social scores per zone across all assessments.</div>', unsafe_allow_html=True)

                if st.button("🔄 Load Zone Risk", key="btn_zone_risk"):
                    status, data = api("GET", "/admin/risk", token=at)
                    show_response(status, data)

        # ── CONFIG ───────────────────────────────────────────────
        with tab_a6:
            st.markdown("### ⚙️ System Configuration")
            st.markdown('<div class="guide-box">💡 Dynamic thresholds stored in <code>system_config</code> table. <b>claim_threshold</b>: minimum fused score to trigger a claim (default 0.5). <b>fraud_threshold</b>: minimum fraud score to flag as suspicious (default 0.3). Every change is audit-logged.</div>', unsafe_allow_html=True)

            if st.button("🔄 Load Current Config", key="btn_load_config"):
                status, data = api("GET", "/admin/config", token=at)
                show_response(status, data)

            st.markdown("---")
            st.markdown("#### Update Config")
            uc1, uc2 = st.columns(2)
            with uc1:
                new_claim_thresh = st.text_input("claim_threshold", value="0.5", key="new_ct")
            with uc2:
                new_fraud_thresh = st.text_input("fraud_threshold", value="0.3", key="new_ft")

            if st.button("💾 Update Config", key="btn_update_config", type="primary"):
                status, data = api("PUT", "/admin/config", token=at, data={
                    "configs": [
                        {"key": "claim_threshold", "value": new_claim_thresh},
                        {"key": "fraud_threshold", "value": new_fraud_thresh},
                    ]
                })
                show_response(status, data)

        # ── ANALYTICS ────────────────────────────────────────────
        with tab_a7:
            st.markdown("### 📈 Analytics Overview")
            st.markdown('<div class="guide-box">💡 Aggregates data from <code>daily_metrics</code>, <code>zone_metrics</code>, and <code>claims</code> tables. Shows daily trends, top zones by claims, payout distribution, and approval rate.</div>', unsafe_allow_html=True)

            if st.button("🔄 Load Analytics", key="btn_analytics", use_container_width=True):
                status, data = api("GET", "/admin/analytics", token=at)
                show_response(status, data)
                if status == 200:
                    summary = data.get("summary", {})
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total Claims", summary.get("total_claims", 0))
                    c2.metric("Approval Rate", f"{summary.get('approval_rate', 0)}%")
                    c3.metric("Avg Payout", f"₹{summary.get('avg_payout', 0):.0f}")

                    st.markdown("#### Top Zones")
                    for z in data.get("top_zones", []):
                        st.markdown(f"- **{z['zone']}**: {z['claim_count']} claims, ₹{z['total_payout']:.0f} payout")

        # ── AUDIT ────────────────────────────────────────────────
        with tab_a8:
            st.markdown("### 📝 Audit Trail & Notifications")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("#### Audit Logs")
                st.markdown('<div class="guide-box">💡 Every admin action is recorded: who did what, to which entity, with old and new data. Essential for compliance and governance.</div>', unsafe_allow_html=True)

                if st.button("🔄 Load Audit Logs", key="btn_audit"):
                    status, data = api("GET", "/admin/audit-logs", token=at)
                    show_response(status, data)

            with col2:
                st.markdown("#### Admin Notifications")
                st.markdown('<div class="guide-box">💡 System-generated alerts for admins — fraud alerts, high-risk zones, etc. Separate from worker notifications.</div>', unsafe_allow_html=True)

                if st.button("🔄 Load Admin Notifications", key="btn_admin_notifs"):
                    status, data = api("GET", "/admin/notifications", token=at)
                    show_response(status, data)


# ═══════════════════════════════════════════════════════════════════
# DATABASE VIEWER
# ═══════════════════════════════════════════════════════════════════

elif portal == "🗃️ Database":
    st.markdown("# 🗃️ Database Viewer")
    st.markdown("*Direct view into all 18 SQLite tables*")

    try:
        conn = sqlite3.connect(DB_PATH)

        tables = [
            "auth_users", "auth_sessions", "workers", "policies",
            "claims", "claim_explanations", "fraud_checks", "fraud_flags",
            "risk_signals", "notifications",
            "claim_reviews", "worker_activity_logs", "fraud_alerts",
            "daily_metrics", "zone_metrics", "system_config",
            "audit_logs", "admin_notifications",
        ]

        # Table counts
        st.markdown("### Table Row Counts")
        counts = {}
        for t in tables:
            try:
                c = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                counts[t] = c
            except Exception:
                counts[t] = -1

        cols = st.columns(6)
        for i, (table, count) in enumerate(counts.items()):
            with cols[i % 6]:
                color = "normal" if count > 0 else "off"
                st.metric(table, count)

        st.markdown("---")

        # Browse table
        selected = st.selectbox("Browse Table", tables)
        if st.button("🔄 Load Table Data"):
            try:
                import pandas as pd
                df = pd.read_sql_query(f"SELECT * FROM {selected} ORDER BY rowid DESC LIMIT 50", conn)
                st.dataframe(df, use_container_width=True)
            except Exception as e:
                st.error(f"Error: {e}")

        # Custom query
        st.markdown("---")
        st.markdown("#### 🔧 Custom SQL Query")
        custom_sql = st.text_area("SQL", value="SELECT * FROM auth_users LIMIT 10;", key="custom_sql")
        if st.button("▶️ Run Query"):
            try:
                import pandas as pd
                df = pd.read_sql_query(custom_sql, conn)
                st.dataframe(df, use_container_width=True)
            except Exception as e:
                st.error(f"Error: {e}")

        conn.close()

    except Exception as e:
        st.error(f"Database error: {e}")
