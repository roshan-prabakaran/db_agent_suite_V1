from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from db_agent_suite.api.auth import get_current_user
from db_agent_suite.database.connection import get_master_db_cursor
import json

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

class PinRequest(BaseModel):
    session_id: str
    connection_id: int
    chart_json: str
    title: str

@router.post("/pins")
def add_pin(req: PinRequest, user: dict = Depends(get_current_user)):
    try: json.loads(req.chart_json)
    except: raise HTTPException(status_code=400, detail="Invalid chart JSON")

    try:
        # ensure_table() removed
        with get_master_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO pinned_charts (user_id, session_id, connection_id, title, chart_json)
                VALUES (%s, %s, %s, %s, %s) RETURNING id;
            """, (user["id"], req.session_id, req.connection_id, req.title, req.chart_json))
            pin_id = cur.fetchone()[0]
        return {"id": pin_id, "message": "Chart pinned successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pins")
def list_pins(user: dict = Depends(get_current_user)):
    try:
        # ensure_table() removed
        with get_master_db_cursor() as cur:
            cur.execute("SELECT id, session_id, connection_id, title, chart_json FROM pinned_charts WHERE user_id = %s ORDER BY created_at DESC;", (user["id"],))
            rows = cur.fetchall()
            pins = [{"id": r[0], "session_id": r[1], "connection_id": r[2], "title": r[3], "chart_json": r[4]} for r in rows]
            return {"pins": pins}
    except Exception as e:
        return {"pins": []}

@router.delete("/pins/{pin_id}")
def delete_pin(pin_id: int, user: dict = Depends(get_current_user)):
    try:
        with get_master_db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM pinned_charts WHERE id = %s AND user_id = %s;", (pin_id, user["id"]))
        return {"message": "Deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

