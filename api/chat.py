import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db_agent_suite.api.auth import get_current_user
from db_agent_suite.database import history as db_history
from db_agent_suite.agent.db_agent import DBAgent
from db_agent_suite.database.connection import get_master_db_config

router = APIRouter(prefix="/chat", tags=["chat"])
agent = DBAgent()
logger = logging.getLogger("ChatAPI")

class ChatRequest(BaseModel):
    message: str
    session_id: str
    connection_id: Optional[int] = None # None means Master DB

@router.get("/sessions")
def get_sessions(user: dict = Depends(get_current_user)):
    sessions = db_history.get_user_sessions(user["id"])
    return {"sessions": [{"id": s[0], "title": s[1]} for s in sessions]}

@router.get("/history/{session_id}")
def get_session_history(session_id: str, user: dict = Depends(get_current_user)):
    history = db_history.get_history(session_id, user_id=user["id"])
    return {"history": history}

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    success = db_history.clear_history(session_id, user_id=user["id"])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete session")
    return {"message": "Session deleted successfully"}

@router.post("/message")
def send_message(req: ChatRequest, user: dict = Depends(get_current_user)):
    # Load history
    history = db_history.get_history(req.session_id, user_id=user["id"])
    
    # Save user message (skip hidden system messages from the UI)
    if not req.message.startswith("[SYSTEM_HIDDEN]"):
        db_history.add_message(req.session_id, "user", req.message, user_id=user["id"])
    
    # Load ALL connections the user can access — needed for prompt-based switching
    from db_agent_suite.database.queries import load_user_connections
    all_connections = load_user_connections(user["id"], user.get("user_key", ""), user["role"])

    # Resolve the currently-selected connection as the initial active DB
    active_config = None
    active_permissions = {"can_read": True, "can_write": True}

    if not req.connection_id:
        raise HTTPException(status_code=400, detail="A specific database connection must be selected.")

    conn = next((c for c in all_connections if c["id"] == req.connection_id), None)
    if not conn or not conn["usable"]:
        raise HTTPException(status_code=400, detail="Invalid or unusable connection")

    active_config = {
        "host": conn["host"],
        "port": conn["port"],
        "database": conn["database"],
        "user": conn["user"],
        "password": conn["password"],
        "connection_id": conn["id"],
        "connection_name": conn["name"],
    }
    active_permissions = {
        "can_read": conn["can_read"],
        "can_write": conn["can_write"],
        "allowed_tables": conn.get("allowed_tables"),
    }

    result = agent.run(
        user_prompt=req.message,
        session_history=history,
        session_id=req.session_id,
        db_config=active_config,
        permissions=active_permissions,
        available_connections=all_connections,   # ← full list for switching
        user_info={"id": user["id"], "user_key": user.get("user_key", ""), "role": user.get("role", "")}
    )

    logger.info(f"Agent result status: {result.get('status')}, messages count: {len(result.get('messages', []))}")
    
    if result["status"] == "error":
        msg = f"Error: {result['message']}"
        db_history.add_message(req.session_id, "assistant", msg, user_id=user["id"])
        return {"status": "error", "message": msg}
        
    if result["status"] == "pending_approval":
        return {
            "status": "pending_approval",
            "pending_sql": result["pending_sql"]
        }
        
    # Save new agent messages
    all_result_msgs = result.get("messages", [])
    
    # We only want the NEW messages generated during this run.
    # Find the index of the LAST user message in the LangGraph state.
    # Everything after it is what the agent generated just now.
    last_user_idx = -1
    for i in range(len(all_result_msgs) - 1, -1, -1):
        msg = all_result_msgs[i]
        role = msg.type if hasattr(msg, "type") else msg.get("role", "")
        if role in ("human", "user"):
            last_user_idx = i
            break
            
    new_msgs_raw = all_result_msgs[last_user_idx + 1:] if last_user_idx != -1 else []

    new_messages = []
    for new_msg in new_msgs_raw:
        content_str = getattr(new_msg, "content", "") or ""
        
        # Skip internal messages that only contain tool calls or are empty
        if not content_str:
            continue

        role = new_msg.type if hasattr(new_msg, "type") else new_msg.get("role", "assistant")
        if role == "ai":
            role = "assistant"
            
        db_history.add_message(req.session_id, role, content_str, user_id=user["id"])

        # Normalize for the frontend
        if role in ("ai", "assistant"):
            new_messages.append({"role": "assistant", "content": content_str})

    from db_agent_suite.agent.tools import get_session_db_config
    session_config = get_session_db_config(req.session_id)
    switched_id = session_config.get("connection_id") if session_config else None

    return {
        "status": "success", 
        "new_messages": new_messages,
        "switched_connection_id": switched_id
    }
class ApproveRequest(BaseModel):
    session_id: str
    approved: bool
    connection_id: Optional[int] = None

@router.post("/approve")
def approve_query(req: ApproveRequest, user: dict = Depends(get_current_user)):
    """Resume the agent graph after a pending human-in-the-loop approval."""
    active_config = None
    active_permissions = {"can_read": True, "can_write": True}

    if req.connection_id:
        from db_agent_suite.database.queries import load_user_connections
        connections = load_user_connections(user["id"], user["user_key"], user["role"])
        conn = next((c for c in connections if c["id"] == req.connection_id), None)
        if conn:
            active_config = {"host": conn["host"], "port": conn["port"], "database": conn["database"], "user": conn["user"], "password": conn["password"]}
            active_permissions = {"can_read": conn["can_read"], "can_write": conn["can_write"], "allowed_tables": conn.get("allowed_tables")}

    result = agent.resume(approved=req.approved, session_id=req.session_id, db_config=active_config, permissions=active_permissions)

    logger.info(f"Approve result: {result.get('status')}")

    if result["status"] == "error":
        return {"status": "error", "message": result["message"]}

    if result["status"] == "pending_approval":
        return {"status": "pending_approval", "pending_sql": result["pending_sql"]}

    all_result_msgs = result.get("messages", [])
    last_user_idx = -1
    for i in range(len(all_result_msgs) - 1, -1, -1):
        msg = all_result_msgs[i]
        role = msg.type if hasattr(msg, "type") else msg.get("role", "")
        if role in ("human", "user"):
            last_user_idx = i
            break

    new_msgs_raw = all_result_msgs[last_user_idx + 1:] if last_user_idx != -1 else []
    new_messages = []
    for new_msg in new_msgs_raw:
        content_str = getattr(new_msg, "content", "") or ""
        
        if not content_str:
            continue
            
        role = new_msg.type if hasattr(new_msg, "type") else new_msg.get("role", "assistant")
        if role == "ai":
            role = "assistant"
            
        db_history.add_message(req.session_id, role, content_str, user_id=user["id"])
        
        if role in ("ai", "assistant"):
            new_messages.append({"role": "assistant", "content": content_str})

    return {"status": "success", "new_messages": new_messages}
