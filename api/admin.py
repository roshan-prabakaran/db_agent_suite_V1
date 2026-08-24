from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import psycopg2
from db_agent_suite.api.auth import get_current_user
from db_agent_suite.database.queries import get_employees, set_employee_permission, get_connection_cipher_key, decrypt_data, save_user_connection
from db_agent_suite.database.connection import get_master_db_cursor

router = APIRouter(prefix="/admin", tags=["admin"])

class PermissionRequest(BaseModel):
    connection_id: int
    employee_id: int
    can_read: bool
    can_write: bool
    can_create_tables: bool = False
    allowed_tables: Optional[List[str]] = None

class GlobalPermRequest(BaseModel):
    employee_id: int
    can_add_db: bool

class NewDBForEmployeeRequest(BaseModel):
    """Create a new DB connection owned by admin and immediately grant it to an employee."""
    employee_id: int
    name: str
    host: str
    port: int
    database: str
    user: str
    password: str
    can_read: bool = True
    can_write: bool = False
    can_create_tables: bool = False

def require_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

@router.get("/employees")
def list_employees(user: dict = Depends(require_admin)):
    rows = get_employees()
    return {"employees": [{"id": r[0], "email": r[1]} for r in rows]}

@router.get("/connections")
def list_all_connections(user: dict = Depends(require_admin)):
    """Admin sees ALL connections in the system."""
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute("SELECT id, name, host, port, database_name FROM db_connections ORDER BY name;")
            rows = cursor.fetchall()
        return {"connections": [{"id": r[0], "name": r[1], "host": r[2], "port": r[3], "database": r[4]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/connections")
def create_connection_for_employee(req: NewDBForEmployeeRequest, user: dict = Depends(require_admin)):
    """
    Admin creates a new DB connection and immediately grants it to a specific employee.
    The connection is owned by the admin (user["id"]) and the employee gets
    the specified permissions in one atomic operation.
    """
    # Test the connection first before saving
    try:
        test_conn = psycopg2.connect(
            host=req.host, port=req.port, dbname=req.database,
            user=req.user, password=req.password, connect_timeout=5
        )
        test_conn.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot connect to database: {e}")

    # Save the connection (owned by admin)
    conn_id = save_user_connection(
        user_id=user["id"],
        name=req.name,
        conn_config={
            "host": req.host, "port": req.port,
            "database": req.database, "user": req.user, "password": req.password
        },
        user_key=user.get("user_key", "")
    )
    if not conn_id:
        raise HTTPException(status_code=500, detail="Failed to save connection")

    # Immediately grant access to the employee
    try:
        set_employee_permission(
            connection_id=conn_id,
            employee_id=req.employee_id,
            can_read=req.can_read,
            can_write=req.can_write,
            can_create_tables=req.can_create_tables,
            allowed_tables=None,  # all tables initially
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection created but failed to assign permissions: {e}")

    return {"message": "Connection created and access granted", "connection_id": conn_id}

def _get_conn_creds(connection_id: int):
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute("SELECT host, port, database_name, username, encrypted_password FROM db_connections WHERE id = %s;", (connection_id,))
            row = cursor.fetchone()
        if not row:
            return None
        password = decrypt_data(row[4], get_connection_cipher_key())
        return {"host": row[0], "port": row[1], "database": row[2], "user": row[3], "password": password}
    except:
        return None

@router.get("/tables/{connection_id}")
def get_connection_tables(connection_id: int, user: dict = Depends(require_admin)):
    creds = _get_conn_creds(connection_id)
    if not creds:
        raise HTTPException(status_code=400, detail="Connection not found or credentials unreadable")
    try:
        conn = psycopg2.connect(host=creds["host"], port=creds["port"], dbname=creds["database"], user=creds["user"], password=creds["password"], connect_timeout=5)
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")
            tables = [r[0] for r in cur.fetchall()]
        conn.close()
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch tables: {e}")

@router.get("/permissions/{employee_id}")
def get_employee_permissions(employee_id: int, user: dict = Depends(require_admin)):
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute("ALTER TABLE db_connection_permissions ADD COLUMN IF NOT EXISTS allowed_tables TEXT[] DEFAULT NULL;")
            cursor.execute("ALTER TABLE db_connection_permissions ADD COLUMN IF NOT EXISTS can_create_tables BOOLEAN DEFAULT FALSE;")
            cursor.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS can_add_db BOOLEAN DEFAULT FALSE;")
            cursor.connection.commit()
            cursor.execute("""
                SELECT connection_id, can_read, can_write, allowed_tables,
                       COALESCE(can_create_tables, FALSE)
                FROM db_connection_permissions WHERE employee_id = %s;
            """, (employee_id,))
            rows = cursor.fetchall()
            cursor.execute("SELECT COALESCE(can_add_db, FALSE) FROM auth_users WHERE id = %s;", (employee_id,))
            add_db_row = cursor.fetchone()
        perms = {}
        for r in rows:
            perms[r[0]] = {"can_read": bool(r[1]), "can_write": bool(r[2]), "allowed_tables": list(r[3]) if r[3] else None, "can_create_tables": bool(r[4])}
        return {"permissions": perms, "can_add_db": bool(add_db_row[0]) if add_db_row else False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/permissions")
def assign_permission(req: PermissionRequest, user: dict = Depends(require_admin)):
    try:
        set_employee_permission(
            req.connection_id, req.employee_id, req.can_read, req.can_write,
            allowed_tables=req.allowed_tables if req.allowed_tables else None,
            can_create_tables=req.can_create_tables
        )
        return {"message": "Permission updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/global-permissions")
def set_global_permission(req: GlobalPermRequest, user: dict = Depends(require_admin)):
    """Set global user-level permissions like can_add_db."""
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS can_add_db BOOLEAN DEFAULT FALSE;")
            cursor.execute("UPDATE auth_users SET can_add_db = %s WHERE id = %s;", (req.can_add_db, req.employee_id))
        return {"message": "Global permission updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

