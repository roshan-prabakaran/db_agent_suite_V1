import os
import sys
import uuid
import pandas as pd
import streamlit as st
from pathlib import Path

# Ensure the parent directory is in sys.path so absolute imports resolve correctly
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# Set page configuration with a premium dark-mode title and icon
st.set_page_config(
    page_title="Deep DB Agent & LLM Gateway Suite",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Claude-Style Premium CSS overrides
st.markdown("""
<style>
    /* Global styling */
    .stApp {
        background-color: #0b0d11;
        color: #e2e8f0;
        font-family: 'Inter', -apple-system, sans-serif;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #11141a !important;
        border-right: 1px solid #1f242e;
    }
    section[data-testid="stSidebar"] .stMarkdown h2 {
        font-size: 1.4rem;
        font-weight: 700;
        color: #a78bfa;
    }
    
    /* Clean headers */
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #c084fc 0%, #6366f1 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .subtitle {
        color: #94a3b8;
        font-size: 1.0rem;
        margin-bottom: 1.5rem;
    }
    
    /* Card/Section design */
    .premium-card {
        background-color: #171b26;
        border: 1px solid #283046;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 15px;
    }
    
    /* Status indicators */
    .status-badge {
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-online {
        background-color: #064e3b;
        color: #34d399;
    }
    .status-offline {
        background-color: #7f1d1d;
        color: #f87171;
    }
    
    /* Chat bubbles styling */
    .chat-bubble {
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 12px;
        max-width: 85%;
        line-height: 1.5;
    }
    .chat-user {
        background-color: #1e293b;
        color: #f1f5f9;
        margin-left: auto;
        border-bottom-right-radius: 2px;
    }
    .chat-assistant {
        background-color: #171c26;
        color: #f1f5f9;
        margin-right: auto;
        border-bottom-left-radius: 2px;
        border: 1px solid #283046;
    }
    
    /* Approval boxes */
    .approval-container {
        border-left: 4px solid #eab308;
        background-color: #1c1917;
        border-radius: 6px;
        padding: 18px;
        margin: 20px 0;
        border-top: 1px solid #292524;
        border-bottom: 1px solid #292524;
        border-right: 1px solid #292524;
    }
    
    /* Buttons */
    .stButton>button {
        border-radius: 6px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease-in-out !important;
    }
    .stButton>button:hover {
        transform: translateY(-1px);
    }
</style>
""", unsafe_allow_html=True)

# Imports from package
from db_agent_suite import config
from db_agent_suite.database.connection import get_master_db_config, get_connection_pool, test_connection, get_master_db_cursor
from db_agent_suite.database.schema import initialize_database
from db_agent_suite.database import history as db_history
from db_agent_suite.cache.redis_client import cache_client
from db_agent_suite.agent.db_agent import DBAgent
from db_agent_suite.agent import tools
from db_agent_suite.utils.observability import obs_manager
from db_agent_suite.utils.security import (
    hash_password,
    verify_password,
    derive_encryption_key,
    encrypt_data,
    decrypt_data,
)
import logging
logger = logging.getLogger(__name__)

# -------------------------------------------------------------
# INITIALIZE SESSION STATE
# -------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None  # Will hold {"id": 1, "email": "..."}
if "user_key" not in st.session_state:
    st.session_state.user_key = None  # Key derived from password (not persisted)
if "db_connected" not in st.session_state:
    st.session_state.db_connected = False
if "active_db_config" not in st.session_state:
    st.session_state.active_db_config = None
if "active_db_name" not in st.session_state:
    st.session_state.active_db_name = "Master Database"
if "saved_connections" not in st.session_state:
    st.session_state.saved_connections = []
if "session_id" not in st.session_state:
    st.session_state.session_id = "default_session"
if "agent_history" not in st.session_state:
    st.session_state.agent_history = []
if "pending_approval_sql" not in st.session_state:
    st.session_state.pending_approval_sql = None
if "pending_target" not in st.session_state:
    st.session_state.pending_target = None

# -------------------------------------------------------------
# MASTER DATABASE CHECK
# -------------------------------------------------------------
try:
    master_ok, master_msg = test_connection(get_master_db_config())
    if master_ok:
        st.session_state.db_connected = True
    else:
        raise ConnectionError(master_msg)
except Exception as e:
    logger.error(f"Failed to connect to master database: {e}")
    st.error("⛔ FATAL: Master Database Unreachable")
    st.write("Could not connect to the master PostgreSQL database required for authentication and state management.")
    st.write(f"**Error:** `{e}`")
    st.write("Please check your environment variables: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.")
    st.stop()


# -------------------------------------------------------------
# SECURE HELPER QUERIES FOR AUTH & CONFIGURATION
# -------------------------------------------------------------
def get_user_by_email(email: str):
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute("SELECT id, email, password_hash, account_role FROM auth_users WHERE email = %s;", (email,))
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "email": row[1], "password_hash": row[2], "role": row[3]}
    except Exception as e:
        st.error(f"Database query error: {e}")
    return None

def create_user(email: str, password_raw: str):
    p_hash = hash_password(password_raw)
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT COUNT(*) FROM auth_users;")
            role = "admin" if cursor.fetchone()[0] == 0 else "employee"
            cursor.execute(
                "INSERT INTO auth_users (email, password_hash, account_role) VALUES (%s, %s, %s) RETURNING id;",
                (email, p_hash, role)
            )
            uid = cursor.fetchone()[0]
            return uid, role
    except Exception as e:
        st.error(f"Failed to register user: {e}")
    return None


def get_connection_cipher_key() -> str:
    """Stable service key so a permitted employee can use an admin-owned target."""
    secret = config.DB_CONNECTION_ENCRYPTION_SECRET
    if not secret:
        secret = config.POSTGRES_PASSWORD
    return derive_encryption_key(secret, "db-agent-suite:connection-credentials:v1")


def migrate_connection_password(connection_id: int, password: str):
    """Upgrade a legacy owner-encrypted connection after its owner signs in."""
    with get_master_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE db_connections SET encrypted_password = %s WHERE id = %s;",
            (encrypt_data(password, get_connection_cipher_key()), connection_id),
        )

def load_user_connections(user_id: int, user_key: str, role: str):
    try:
        with get_master_db_cursor() as cursor:
            if role == "admin":
                cursor.execute("SELECT id, name, host, port, database_name, username, encrypted_password, TRUE, TRUE FROM db_connections WHERE user_id = %s ORDER BY name;", (user_id,))
            else:
                cursor.execute("""
                    SELECT c.id, c.name, c.host, c.port, c.database_name, c.username,
                           c.encrypted_password, p.can_read, p.can_write
                    FROM db_connections c
                    JOIN db_connection_permissions p ON p.connection_id = c.id
                    WHERE p.employee_id = %s AND (p.can_read OR p.can_write)
                    ORDER BY c.name;
                """, (user_id,))
            rows = cursor.fetchall()
            connections = []
            for r in rows:
                dec_pass = ""
                try:
                    dec_pass = decrypt_data(r[6], get_connection_cipher_key())
                except Exception:
                    try:
                        dec_pass = decrypt_data(r[6], user_key)
                        migrate_connection_password(r[0], dec_pass)
                    except Exception:
                        dec_pass = ""
                connections.append({
                    "id": r[0],
                    "name": r[1],
                    "host": r[2],
                    "port": r[3],
                    "database": r[4],
                    "user": r[5],
                    "password": dec_pass,
                    "usable": bool(dec_pass),
                    "can_read": r[7],
                    "can_write": r[8],
                })
            return connections
    except Exception as e:
        st.error(f"Failed to load saved connections: {e}")
    return []

def save_user_connection(user_id: int, name: str, conn_config: dict, user_key: str):
    enc_pass = encrypt_data(conn_config["password"], get_connection_cipher_key())
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute(
                """INSERT INTO db_connections (user_id, name, host, port, database_name, username, encrypted_password)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;""",
                (user_id, name, conn_config["host"], conn_config["port"], conn_config["database"], conn_config["user"], enc_pass)
            )
            return cursor.fetchone()[0]
    except Exception as e:
        st.error(f"Failed to save connection: {e}")
    return None

def delete_user_connection(conn_id: int, user_id: int):
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM db_connections WHERE id = %s AND user_id = %s;", (conn_id, user_id))
            return True
    except Exception as e:
        st.error(f"Failed to delete connection: {e}")
    return False


def get_employees():
    with get_master_db_cursor() as cursor:
        cursor.execute("SELECT id, email FROM auth_users WHERE account_role = 'employee' ORDER BY email;")
        return cursor.fetchall()


def set_employee_permission(connection_id: int, employee_id: int, can_read: bool, can_write: bool):
    with get_master_db_cursor(commit=True) as cursor:
        cursor.execute("""
            INSERT INTO db_connection_permissions (connection_id, employee_id, can_read, can_write)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (connection_id, employee_id)
            DO UPDATE SET can_read = EXCLUDED.can_read, can_write = EXCLUDED.can_write;
        """, (connection_id, employee_id, can_read, can_write))


def begin_user_chat_session():
    """Prevent a previous account's in-memory chat from leaking into a new login."""
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.agent_history = []
    st.session_state.pending_approval_sql = None
    st.session_state.pending_target = None
    st.session_state.active_db_config = None
    st.session_state.active_db_name = "Master Database"


# -------------------------------------------------------------
# AUTHENTICATION SCREEN (Login & Signup)
# -------------------------------------------------------------
if not st.session_state.authenticated:
    st.markdown("""
    <div style='text-align: center; margin-top: 60px;'>
        <h1 style='font-size: 2.8rem; font-weight:800; background: linear-gradient(135deg, #a78bfa 0%, #3b82f6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>🤖 Deep DB Agent Portal</h1>
        <p style='color:#94a3b8; font-size:1.1rem;'>Connect your database safely. Protected by Prompt Injection Guardrails & Observability.</p>
    </div>
    """, unsafe_allow_html=True)
    
    tab_login, tab_signup = st.tabs(["🔑 Sign In", "👤 Create Account"])
    
    with tab_login:
        with st.container():
            st.markdown("<div class='premium-card' style='max-width: 450px; margin: 0 auto;'>", unsafe_allow_html=True)
            email_input = st.text_input("Email Address", key="login_email")
            password_input = st.text_input("Password", type="password", key="login_pass")
            
            if st.button("Log In", use_container_width=True, type="primary"):
                user_record = get_user_by_email(email_input)
                if user_record and verify_password(password_input, user_record["password_hash"]):
                    st.session_state.authenticated = True
                    st.session_state.user = {"id": user_record["id"], "email": user_record["email"], "role": user_record["role"]}
                    st.session_state.user_key = derive_encryption_key(password_input, email_input)
                    st.session_state.saved_connections = load_user_connections(user_record["id"], st.session_state.user_key, user_record["role"])
                    begin_user_chat_session()
                    st.success("Successfully logged in!")
                    st.rerun()
                else:
                    st.error("Invalid email or password.")
            st.markdown("</div>", unsafe_allow_html=True)
            
    with tab_signup:
        with st.container():
            st.markdown("<div class='premium-card' style='max-width: 450px; margin: 0 auto;'>", unsafe_allow_html=True)
            reg_email = st.text_input("Email Address", key="reg_email")
            reg_pass = st.text_input("Password", type="password", key="reg_pass")
            reg_pass_conf = st.text_input("Confirm Password", type="password", key="reg_pass_conf")
            
            if st.button("Create Account", use_container_width=True):
                if not reg_email or not reg_pass:
                    st.error("Please fill out all fields.")
                elif reg_pass != reg_pass_conf:
                    st.error("Passwords do not match.")
                elif get_user_by_email(reg_email):
                    st.error("Account already exists with this email.")
                else:
                    created = create_user(reg_email, reg_pass)
                    if created:
                        uid, role = created
                        st.session_state.authenticated = True
                        st.session_state.user = {"id": uid, "email": reg_email, "role": role}
                        st.session_state.user_key = derive_encryption_key(reg_pass, reg_email)
                        st.session_state.saved_connections = []
                        begin_user_chat_session()
                        st.success("Account created successfully!")
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# -------------------------------------------------------------
# MAIN APP & SIDEBAR REDESIGN (Claude Style)
# -------------------------------------------------------------
st.sidebar.markdown(f"## 👤 {st.session_state.user['email']}")
st.sidebar.caption("Administrator" if st.session_state.user["role"] == "admin" else "Employee")
if st.sidebar.button("🚪 Log Out", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.user = None
    st.session_state.user_key = None
    st.session_state.active_db_config = None
    st.session_state.active_db_name = "Master Database"
    st.session_state.saved_connections = []
    begin_user_chat_session()
    st.rerun()

st.sidebar.markdown("---")

# 1. Active Connection Switching
st.sidebar.markdown("### 🔌 Database Connection")
db_options = (["Master Database"] if st.session_state.user["role"] == "admin" else []) + [conn["name"] for conn in st.session_state.saved_connections]
if not db_options:
    st.sidebar.warning("No database has been assigned to your account yet.")
    st.stop()
selected_option = st.sidebar.selectbox("Active Target Database", db_options, index=db_options.index(st.session_state.active_db_name) if st.session_state.active_db_name in db_options else 0)

if selected_option != st.session_state.active_db_name:
    st.session_state.active_db_name = selected_option
    if selected_option == "Master Database":
        st.session_state.active_db_config = None
    else:
        match = next(conn for conn in st.session_state.saved_connections if conn["name"] == selected_option)
        st.session_state.active_db_config = {
            "host": match["host"],
            "port": match["port"],
            "database": match["database"],
            "user": match["user"],
            "password": match["password"]
        }
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.agent_history = []
    st.session_state.pending_approval_sql = None
    st.session_state.pending_target = None
    st.rerun()

if selected_option == "Master Database":
    active_permissions = {"can_read": True, "can_write": True}
    active_target_available = True
else:
    active_connection = next(conn for conn in st.session_state.saved_connections if conn["name"] == selected_option)
    active_permissions = {"can_read": bool(active_connection["can_read"]), "can_write": bool(active_connection["can_write"])}
    active_target_available = bool(active_connection["usable"])

# Connected status indicator
active_conn_ok = active_target_available
if active_conn_ok:
    st.sidebar.markdown("<span class='status-badge status-online'>🟢 Connected</span>", unsafe_allow_html=True)
else:
    st.sidebar.markdown("<span class='status-badge status-offline'>🔴 Disconnected</span>", unsafe_allow_html=True)
    st.sidebar.caption("Connection password is unavailable. An administrator must re-save this connection.")

st.sidebar.markdown("---")

# 2. Connection Manager — administrators own and share target connections.
if st.session_state.user["role"] == "admin":
    with st.sidebar.expander("🛠️ Manage Database Connections"):
        st.write("##### Add New Connection")
        conn_name = st.text_input("Name", placeholder="Production Analytics")
        conn_host = st.text_input("Host", placeholder="localhost")
        conn_port = st.text_input("Port", value="5432")
        conn_db = st.text_input("Database Name", placeholder="postgres")
        conn_user = st.text_input("Username", placeholder="postgres")
        conn_pass = st.text_input("Password", type="password")
    
        if st.button("Save Connection", use_container_width=True):
            if not conn_name or not conn_host or not conn_db or not conn_user or not conn_pass:
                st.error("Name, host, database, username, and password are all required.")
            else:
                test_conf = {
                "host": conn_host,
                "port": conn_port,
                "database": conn_db,
                "user": conn_user,
                "password": conn_pass
                }
                cid = save_user_connection(st.session_state.user["id"], conn_name, test_conf, st.session_state.user_key)
                if cid:
                    st.success(f"Connection '{conn_name}' saved!")
                    st.session_state.saved_connections = load_user_connections(st.session_state.user["id"], st.session_state.user_key, st.session_state.user["role"])
                    st.rerun()

        if st.session_state.saved_connections:
            st.write("##### Delete Saved Connection")
            del_target = st.selectbox("Select to delete", [conn["name"] for conn in st.session_state.saved_connections])
            if st.button("🗑️ Delete Selected", use_container_width=True, type="secondary"):
                target_obj = next(conn for conn in st.session_state.saved_connections if conn["name"] == del_target)
                if delete_user_connection(target_obj["id"], st.session_state.user["id"]):
                    st.success("Deleted!")
                    st.session_state.saved_connections = load_user_connections(st.session_state.user["id"], st.session_state.user_key, st.session_state.user["role"])
                    if st.session_state.active_db_name == del_target:
                        st.session_state.active_db_name = "Master Database"
                        st.session_state.active_db_config = None
                    st.rerun()

    with st.sidebar.expander("🛡️ Employee Access"):
        employees = get_employees()
        connections = st.session_state.saved_connections
        if not employees or not connections:
            st.caption("Create an employee account and at least one connection to manage access.")
        else:
            employee = st.selectbox("Employee", employees, format_func=lambda row: row[1])
            connection = st.selectbox("Database", connections, format_func=lambda row: row["name"])
            can_read = st.checkbox("Allow analysis and schema access", value=True)
            can_write = st.checkbox("Allow approved data changes", value=False)
            if st.button("Save employee access", use_container_width=True):
                set_employee_permission(connection["id"], employee[0], can_read or can_write, can_write)
                st.success("Employee access updated.")
else:
    st.sidebar.caption("Your database access is managed by an administrator.")

st.sidebar.markdown("---")

# 3. Chat Session Manager
st.sidebar.markdown("### 💬 Chat History")
if st.sidebar.button("➕ New Chat Session", use_container_width=True):
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.agent_history = []
    st.session_state.pending_approval_sql = None
    st.session_state.pending_target = None
    st.rerun()

from db_agent_suite.database import history as db_history
user_sessions = db_history.get_user_sessions(st.session_state.user["id"])
if user_sessions:
    st.sidebar.write("Recent Chats:")
    for s_id, session_title in user_sessions[:10]:
        btn_label = f"💬 {session_title}"
        if s_id == st.session_state.session_id:
            st.sidebar.markdown(f"**👉 {btn_label}**")
        else:
            if st.sidebar.button(btn_label, key=f"session_btn_{s_id}", use_container_width=True):
                st.session_state.session_id = s_id
                st.session_state.agent_history = db_history.get_history(s_id, user_id=st.session_state.user["id"])
                st.session_state.pending_approval_sql = None
                st.session_state.pending_target = None
                st.rerun()


# -------------------------------------------------------------
# MAIN APP BODY - Claude Style Layout
# -------------------------------------------------------------
st.markdown("<h1 class='main-title'>🤖 Deep SQL DB Agent</h1>", unsafe_allow_html=True)
st.markdown(f"<p class='subtitle'>Active Connection: <strong>{st.session_state.active_db_name}</strong> | Chat Session: <strong>{st.session_state.session_id}</strong></p>", unsafe_allow_html=True)

# Tabs (Now just the chat, removed Operations tab)
tab_chat, = st.tabs(["💬 Database Assistant"])

# --- TAB 1: Assistant Chat ---
with tab_chat:
    # Initialize Agent
    agent = DBAgent()
    
    # Render diagnostics fallback messages
    fallback_logs = agent.gateway.get_fallback_logs()
    if fallback_logs:
        for log in fallback_logs:
            st.warning(f"⚠️ **LLM Gateway Fallback Triggered!** Model `{log['failed_model']}` failed. Routed to next available fallback. (Error: {log['error']})")
        agent.gateway.clear_fallback_logs()

    # Load history from Database if empty
    if not st.session_state.agent_history:
        st.session_state.agent_history = db_history.get_history(st.session_state.session_id, user_id=st.session_state.user["id"])

    # Render History messages with premium bubbles
    for msg in st.session_state.agent_history:
        if hasattr(msg, "type"):
            role = msg.type
            content = msg.content
            tool_calls = getattr(msg, "tool_calls", None)
            is_tool = role == "tool"
        else:
            role = msg.get("role", "")
            content = msg.get("content", "")
            tool_calls = "tool_calls" in msg
            is_tool = role == "tool"

        if role == "system" or is_tool or tool_calls:
            continue

        st_role = "user" if role in ["user", "human"] else "assistant"
        with st.chat_message(st_role):
            st.markdown(str(content))

    # Handle pending approvals
    if st.session_state.pending_approval_sql:
        st.warning(f"Database write authorization required for {st.session_state.pending_target['name']}.")
        st.code(st.session_state.pending_approval_sql, language="sql")
        
        col_app, col_rej, _ = st.columns([1, 1, 8])
        if col_app.button("✅ Approve & Run Query", type="primary", use_container_width=True):
            with st.spinner("Executing write transaction..."):
                result = agent.resume(approved=True, session_id=st.session_state.session_id,
                                      db_config=st.session_state.pending_target["config"],
                                      permissions=st.session_state.pending_target["permissions"])
            
            # Save new messages
            for new_msg in result.get("messages", [])[len(st.session_state.agent_history):]:
                content_str = getattr(new_msg, "content", "") or ""
                if not content_str and getattr(new_msg, "tool_calls", None):
                    content_str = f"Executed tool: {new_msg.tool_calls[0]['name']}"
                
                db_history.add_message(
                    st.session_state.session_id,
                    new_msg.type if hasattr(new_msg, "type") else new_msg.get("role", "assistant"),
                    content_str,
                    user_id=st.session_state.user["id"]
                )
            
            st.session_state.agent_history = result.get("messages", [])
            st.session_state.pending_approval_sql = None
            st.session_state.pending_target = None
            st.rerun()

        if col_rej.button("❌ Reject Execution", type="secondary", use_container_width=True):
            with st.spinner("Sending rejection back to agent..."):
                result = agent.resume(approved=False, session_id=st.session_state.session_id,
                                      db_config=st.session_state.pending_target["config"],
                                      permissions=st.session_state.pending_target["permissions"])
            
            for new_msg in result.get("messages", [])[len(st.session_state.agent_history):]:
                content_str = getattr(new_msg, "content", "") or ""
                db_history.add_message(
                    st.session_state.session_id,
                    new_msg.type if hasattr(new_msg, "type") else new_msg.get("role", "assistant"),
                    content_str,
                    user_id=st.session_state.user["id"]
                )
            
            st.session_state.agent_history = result.get("messages", [])
            st.session_state.pending_approval_sql = None
            st.session_state.pending_target = None
            st.rerun()

    # Regular input box
    else:
        if not active_conn_ok:
            st.error("Select a working database connection before starting a conversation.")
        user_input = st.chat_input(
            "Ask a question about the selected database…",
            disabled=not active_conn_ok,
        )
        
        auto_analyze = False
        if not st.session_state.agent_history and active_conn_ok and not user_input:
            auto_analyze = True
            user_input = "Please analyze the connected database and provide a brief summary of the schema, including the main tables and their purpose."

        if user_input:
            # Display user message instantly
            with st.chat_message("user"):
                st.markdown(user_input)
            
            db_history.add_message(st.session_state.session_id, "user", user_input, user_id=st.session_state.user["id"])
            st.session_state.agent_history.append({"role": "user", "content": user_input})
            
            with st.spinner("Agent is exploring the database schema..." if auto_analyze else "Agent is reasoning and planning SQL executions..."):
                result = agent.run(
                    user_prompt=user_input,
                    session_history=st.session_state.agent_history[:-1],
                    session_id=st.session_state.session_id,
                    db_config=st.session_state.active_db_config or get_master_db_config(),
                    permissions=active_permissions,
                )
            
            if result["status"] == "error":
                st.error(result["message"])
                db_history.add_message(st.session_state.session_id, "assistant", f"Error: {result['message']}", user_id=st.session_state.user["id"])
                st.session_state.agent_history.append({"role": "assistant", "content": f"Error: {result['message']}"})
                st.rerun()
            elif result["status"] == "pending_approval":
                st.session_state.pending_approval_sql = result["pending_sql"]
                st.session_state.pending_target = {
                    "name": st.session_state.active_db_name,
                    "config": dict(st.session_state.active_db_config or get_master_db_config()),
                    "permissions": dict(active_permissions),
                }
                st.session_state.agent_history = result["messages"]
                st.rerun()
            else:
                for new_msg in result.get("messages", [])[len(st.session_state.agent_history):]:
                    content_str = getattr(new_msg, "content", "") or ""
                    if not content_str and getattr(new_msg, "tool_calls", None):
                        content_str = f"Executed tool: {new_msg.tool_calls[0]['name']}"
                    
                    db_history.add_message(
                        st.session_state.session_id,
                        new_msg.type if hasattr(new_msg, "type") else new_msg.get("role", "assistant"),
                        content_str,
                        user_id=st.session_state.user["id"]
                    )
                st.session_state.agent_history = result.get("messages", [])
                st.rerun()

