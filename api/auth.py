
import logging
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel

from db_agent_suite import config
from db_agent_suite.database.queries import get_user_by_email, create_user
from db_agent_suite.utils.security import verify_password
from db_agent_suite.database.queries import migrate_all_legacy_connections
from db_agent_suite.database.sessions import (
    ensure_sessions_table,
    create_session,
    get_session,
    end_session,
    end_all_sessions,
    list_user_sessions,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE_NAME  = "dba_session" 
SESSION_EXPIRE_HOURS = 24

# Ensure the table exists when the module is first imported
ensure_sessions_table()

logger = logging.getLogger("AuthAPI")

# ---------------------------------------------------------------------------
# Dependency — injected into every protected endpoint
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> dict:
    """
    Reads the session cookie, looks up the session in PostgreSQL,
    and returns the full user dict. Raises 401 if invalid or expired.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return session


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response):
    """
    Authenticate a user and create a fully stateful PostgreSQL session.
    The browser receives only the session_id cookie.
    All state (IP, device, role, user_key) lives in user_sessions table.
    """
    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Invalid email or password")

    # Run a one-time migration for any legacy connections encrypted with this password
    
    migrate_all_legacy_connections(user["id"], req.password, user["role"])

    # Extract device metadata from the HTTP request
    ip_address = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.client.host
        or "unknown"
    )
    user_agent = request.headers.get("User-Agent", "")

    # Create fully stateful session in PostgreSQL without storing raw password
    session_id = create_session(
        user_id    = user["id"],
        ip_address = ip_address,
        user_agent = user_agent
    )

    # Set the HttpOnly cookie (browser stores ONLY the opaque session_id)
    response.set_cookie(
        key      = SESSION_COOKIE_NAME,
        value    = session_id,
        httponly = True,
        max_age  = SESSION_EXPIRE_HOURS * 3600,
        samesite = "lax",
        secure   = config.HTTPS_SECURE,  # True in production (HTTPS), False for local dev
    )

    logger.info(f"User {user['email']} logged in from {ip_address}")
    return {
        "message": "Logged in successfully",
        "user": {"id": user["id"], "email": user["email"], "role": user["role"]},
    }


@router.post("/register")
def register(req: RegisterRequest, request: Request, response: Response):
    """Register a new user and immediately log them in."""
    existing = get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    result = create_user(req.email, req.password)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create user")

    return login(LoginRequest(email=req.email, password=req.password), request, response)


@router.post("/logout")
def logout(request: Request, response: Response, user: dict = Depends(get_current_user)):
    """
    End the current session by marking it 'ended' in PostgreSQL
    and deleting the browser cookie.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        end_session(session_id)
    response.delete_cookie(SESSION_COOKIE_NAME)
    logger.info(f"User {user['email']} logged out")
    return {"message": "Logged out successfully"}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, user: dict = Depends(get_current_user)):
    """
    Force-end ALL active sessions for this user (e.g., after password change
    or if the user suspects a compromised session).
    """
    end_all_sessions(user["id"])
    response.delete_cookie(SESSION_COOKIE_NAME)
    logger.info(f"All sessions ended for user {user['email']}")
    return {"message": "All sessions terminated"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's public profile."""
    from db_agent_suite.database.connection import get_master_db_cursor
    is_admin = user.get("role") == "admin"
    can_add_db = is_admin
    if not is_admin:
        try:
            with get_master_db_cursor() as cursor:
                cursor.execute("SELECT COALESCE(can_add_db, FALSE) FROM auth_users WHERE id = %s;", (user["id"],))
                row = cursor.fetchone()
                if row:
                    can_add_db = bool(row[0])
        except Exception:
            pass
    return {"id": user["id"], "email": user["email"], "role": user["role"], "can_add_db": can_add_db}




@router.get("/sessions")
def get_my_sessions(user: dict = Depends(get_current_user)):
    """
    Return the login history for the current user —
    session_id, IP, device, status, created_at, last_active, ended_at.
    Lets users see exactly which devices are currently logged in.
    """
    sessions = list_user_sessions(user["id"])
    return {"sessions": sessions}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, user: dict = Depends(get_current_user)):
    """
    Allow a user to individually revoke a specific session
    (e.g., 'Sign out of Chrome on Android' from their session list).
    """
    # Ensure the session belongs to this user before deleting
    from db_agent_suite.database.sessions import get_session as _gs
    target = _gs(session_id)
    if not target or target["id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Session not found")
    end_session(session_id)
    return {"message": f"Session {session_id[:8]}... revoked"}


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