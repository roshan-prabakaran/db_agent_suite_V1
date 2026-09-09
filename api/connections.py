from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db_agent_suite.database.queries import (
    load_user_connections,
    save_user_connection,
    delete_user_connection,
)
from db_agent_suite.api.auth import get_current_user

router = APIRouter(prefix="/connections", tags=["connections"])

class ConnectionCreate(BaseModel):
    name: str
    host: str
    port: str
    database: str
    user: str
    password: str

@router.get("")
def get_connections(user: dict = Depends(get_current_user)):
    connections = load_user_connections(user["id"], user["role"])
    return {"connections": connections}

@router.post("")
def create_connection(conn: ConnectionCreate, user: dict = Depends(get_current_user)):
    # Employees need can_add_db permission; admins always can
    if user["role"] != "admin":
        from db_agent_suite.database.connection import get_master_db_cursor
        try:
            with get_master_db_cursor() as cursor:
                cursor.execute("SELECT COALESCE(can_add_db, FALSE) FROM auth_users WHERE id = %s;", (user["id"],))
                row = cursor.fetchone()
                if not row or not row[0]:
                    raise HTTPException(status_code=403, detail="You do not have permission to add database connections.")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    config_dict = {"host": conn.host, "port": conn.port, "database": conn.database, "user": conn.user, "password": conn.password}
    from db_agent_suite.database.connection import test_connection
    ok, msg = test_connection(config_dict)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Database connection failed: {msg}")
    cid = save_user_connection(user["id"], conn.name, config_dict)
    if not cid:
        raise HTTPException(status_code=500, detail="Failed to save connection")
    return {"id": cid, "message": "Connection saved successfully"}

@router.delete("/{conn_id}")
def delete_connection(conn_id: int, user: dict = Depends(get_current_user)):
    success = delete_user_connection(conn_id, user["id"])
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete connection or unauthorized")
    return {"message": "Connection deleted"}
