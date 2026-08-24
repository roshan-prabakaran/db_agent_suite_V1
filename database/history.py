"""
database/history.py

Manages storing and retrieving user/assistant message history, linkable to users.
"""

import logging
from db_agent_suite.database.connection import get_master_db_cursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DBHistory")

# Only user and assistant text messages are persisted for LLM context reload
PERSISTABLE_ROLES = {"user", "assistant"}


def get_history(session_id: str, user_id: int = None) -> list:
    """
    Retrieve persisted conversation history for a given session ID, optionally scoped to a user.
    """
    if user_id is not None:
        query = """
        SELECT role, content 
        FROM conversation_history 
        WHERE session_id = %s AND user_id = %s
        ORDER BY id ASC;
        """
        params = (session_id, user_id)
    else:
        query = """
        SELECT role, content 
        FROM conversation_history 
        WHERE session_id = %s
        ORDER BY id ASC;
        """
        params = (session_id,)
        
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [{"role": row[0], "content": row[1]} for row in rows]
    except Exception as e:
        logger.error(f"Error fetching history for session {session_id}: {e}")
        return []


def get_user_sessions(user_id: int) -> list:
    """
    Get a list of (session_id, title) tuples for a user's chat sessions.
    The title is derived from the first user message in that session,
    truncated to 40 characters. Falls back to the session_id if no message found.
    """
    query = """
    SELECT
        ch.session_id,
        MAX(ch.timestamp) as last_activity,
        (
            SELECT content FROM conversation_history
            WHERE session_id = ch.session_id AND user_id = %s AND role = 'user'
            ORDER BY id ASC LIMIT 1
        ) as first_message
    FROM conversation_history ch
    WHERE ch.user_id = %s
    GROUP BY ch.session_id
    ORDER BY last_activity DESC;
    """
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute(query, (user_id, user_id))
            rows = cursor.fetchall()
            sessions = []
            for row in rows:
                s_id = row[0]
                first_msg = row[2]
                if first_msg:
                    # Truncate to 40 chars and clean whitespace
                    title = first_msg.strip().replace("\n", " ")
                    title = title[:40] + "…" if len(title) > 40 else title
                else:
                    title = s_id
                sessions.append((s_id, title))
            return sessions
    except Exception as e:
        logger.error(f"Error fetching sessions for user {user_id}: {e}")
        return []


def add_message(session_id: str, role: str, content: str, user_id: int = None) -> bool:
    """
    Add a message to the database conversation history.
    """
    if role not in PERSISTABLE_ROLES:
        return True   # silently skip internal tool messages
    if not content or not content.strip():
        return True   # skip empty text messages

    query = """
    INSERT INTO conversation_history (session_id, role, content, user_id)
    VALUES (%s, %s, %s, %s);
    """
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute(query, (session_id, role, content, user_id))
            return True
    except Exception as e:
        logger.error(f"Error adding message for session {session_id}: {e}")
        return False


def clear_history(session_id: str, user_id: int = None) -> bool:
    """
    Clear history for a specific session ID, optionally scoped to a user.
    """
    if user_id is not None:
        query = "DELETE FROM conversation_history WHERE session_id = %s AND user_id = %s;"
        params = (session_id, user_id)
    else:
        query = "DELETE FROM conversation_history WHERE session_id = %s;"
        params = (session_id,)
        
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute(query, params)
            return True
    except Exception as e:
        logger.error(f"Error clearing history for session {session_id}: {e}")
        return False


def clean_for_llm(messages: list) -> list:
    """
    Sanitize messages by removing raw tool nodes before forwarding to the LLM router.
    """
    safe = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "tool":
            continue
        if role == "assistant" and "tool_calls" in msg:
            text_content = msg.get("content") or ""
            if text_content.strip():
                safe.append({"role": "assistant", "content": text_content})
            continue
        safe.append(msg)
    return safe
