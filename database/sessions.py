"""
database/sessions.py

Fully stateful session management backed by PostgreSQL.

Each session record stores:
  - session_id   : Random UUID (sent to browser as a cookie)
  - user_id      : FK to auth_users
  - ip_address   : Client IP at login
  - user_agent   : Browser / device string at login
  - device_info  : Human-readable summary (e.g. "Chrome on Windows")
  - user_key     : Encrypted copy of user password (for DB decryption)
  - status       : 'active' or 'ended'
  - created_at   : When session was first created
  - last_active  : Updated on every authenticated request
  - ended_at     : Set when user logs out or session is force-killed
"""
"""
POST /api/auth/login
→ auth.py checks email/password
→ sessions.create_session()
→ random UUID inserted into PostgreSQL
→ UUID set as HTTP-only browser cookie

Protected API request
→ auth.py calls sessions.get_session(cookie UUID)
→ database checks active status + 24-hour inactivity limit
→ last_active updated
→ current user details returned

Logout
→ sessions.end_session()
→ status becomes “ended”
→ browser cookie deleted

Logout all devices
→ sessions.end_all_sessions()
→ every active user session becomes “ended”

"""
import logging
import uuid
from datetime import datetime, timedelta
from db_agent_suite.database.connection import get_master_db_cursor

logger = logging.getLogger("SessionsDB")

SESSION_EXPIRE_HOURS = 24

# ---------------------------------------------------------------------------
# Schema bootstrap (idempotent — runs once on startup via auth.py import)
# ---------------------------------------------------------------------------

def ensure_sessions_table():
    """No-op: user_sessions table already exists in the database."""
    logger.info("user_sessions table ensured.")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_session(user_id: int, ip_address: str, user_agent: str) -> str:
    """
    Persist a new session record in PostgreSQL.
    Returns the session_id to be stored in the browser cookie.
    """
    session_id   = str(uuid.uuid4())
    device_info  = _parse_device(user_agent)

    with get_master_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO user_sessions
                (session_id, user_id, ip_address, user_agent, device_info, status)
            VALUES (%s, %s, %s, %s, %s, 'active');
        """, (session_id, user_id, ip_address, user_agent, device_info))

    logger.info(f"Session created for user_id={user_id} from {ip_address} [{device_info}]")
    return session_id


# ---------------------------------------------------------------------------
# Read — called on EVERY authenticated request
# ---------------------------------------------------------------------------

def get_session(session_id: str) -> dict | None:
    """
    Fetch an active, non-expired session from PostgreSQL.
    Also updates last_active timestamp on every call.
    Returns None if session is missing, ended, or expired.
    """
    expiry_cutoff = datetime.utcnow() - timedelta(hours=SESSION_EXPIRE_HOURS)

    with get_master_db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT s.session_id, s.user_id, s.ip_address, s.user_agent,
                   s.device_info, s.status, s.created_at, s.last_active,
                   u.email, u.account_role
            FROM user_sessions s
            JOIN auth_users u ON u.id = s.user_id
            WHERE s.session_id = %s
              AND s.status = 'active'
              AND s.last_active > %s;
        """, (session_id, expiry_cutoff))
        row = cur.fetchone()
        if not row:
            return None

        # Touch last_active so rolling sessions don't expire mid-use
        cur.execute("""
            UPDATE user_sessions SET last_active = NOW()
            WHERE session_id = %s;
        """, (session_id,))

    return {
        "session_id" : row[0],
        "id"         : row[1],    # user_id
        "ip_address" : row[2],
        "user_agent" : row[3],
        "device_info": row[4],
        "status"     : row[5],
        "created_at" : row[6].isoformat() if row[6] else None,
        "last_active": row[7].isoformat() if row[7] else None,
        "email"      : row[8],
        "role"       : row[9],
    }


# ---------------------------------------------------------------------------
# End — logout (single session)
# ---------------------------------------------------------------------------

def end_session(session_id: str):
    """Maark a specific session as 'ended' with a timestamp."""
    with get_master_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE user_sessions
            SET status = 'ended', ended_at = NOW()
            WHERE session_id = %s;
        """, (session_id,))
    logger.info(f"Session ended: {session_id}")


# ---------------------------------------------------------------------------
# End all — force-logout a user from every device
# ---------------------------------------------------------------------------

def end_all_sessions(user_id: int):
    """Terminate ALL active sessions for a user (e.g., password change)."""
    with get_master_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE user_sessions
            SET status = 'ended', ended_at = NOW()
            WHERE user_id = %s AND status = 'active';
        """, (user_id,))
    logger.info(f"All sessions ended for user_id={user_id}")


# ---------------------------------------------------------------------------
# List — admin / profile view of active sessions
# ---------------------------------------------------------------------------

def list_user_sessions(user_id: int) -> list:
    """
    Return all sessions (active and ended) for a given user.
    Used in the /auth/sessions endpoint so users can see their login history.
    """
    with get_master_db_cursor() as cur:
        cur.execute("""
            SELECT session_id, ip_address, device_info, status, created_at, last_active, ended_at
            FROM user_sessions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 20;
        """, (user_id,))
        rows = cur.fetchall()
    return [
        {
            "session_id" : r[0],
            "ip_address" : r[1],
            "device_info": r[2],
            "status"     : r[3],
            "created_at" : r[4].isoformat() if r[4] else None,
            "last_active": r[5].isoformat() if r[5] else None,
            "ended_at"   : r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Cleanup — prune expired rows (optional scheduled job)
# ---------------------------------------------------------------------------

def cleanup_expired_sessions():
    """Delete sessions that have been inactive for longer than SESSION_EXPIRE_HOURS."""
    expiry_cutoff = datetime.utcnow() - timedelta(hours=SESSION_EXPIRE_HOURS)
    with get_master_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE user_sessions
            SET status = 'ended', ended_at = NOW()
            WHERE status = 'active' AND last_active < %s;
        """, (expiry_cutoff,))
    logger.info("Expired sessions cleaned up.")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_device(user_agent: str) -> str:
    """
    Produce a short human-readable device string from the User-Agent header.
    e.g.  'Chrome on Windows'  |  'Safari on iPhone'  |  'Unknown device'
    """
    if not user_agent:
        return "Unknown device"

    ua = user_agent.lower()

    # OS detection
    if "windows" in ua:
        os_ = "Windows"
    elif "android" in ua:
        os_ = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_ = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_ = "macOS"
    elif "linux" in ua:
        os_ = "Linux"
    else:
        os_ = "Unknown OS"

    # Browser detection
    if "edg/" in ua or "edge/" in ua:
        browser = "Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "chrome" in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    else:
        browser = "Unknown Browser"

    return f"{browser} on {os_}"
