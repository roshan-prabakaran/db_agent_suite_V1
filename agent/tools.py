"""
agent/tools.py

LangChain @tool-decorated database tools for the LangGraph agent.

Tool safety model:
  - list_tables  → always safe
  - get_schema   → always safe
  - query_db     → SELECT only (guardrail enforced)
  - modify_db    → INSERT/UPDATE/DELETE, requires user approval via
                   LangGraph interrupt() before execution
"""

import logging
import re
from contextlib import contextmanager
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from db_agent_suite.database.connection import get_db_cursor
from db_agent_suite.gateway.guardrails import analyze_sql_safety

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AgentTools")

# =============================================================
# APPROVED QUERIES
# Set populated by app.py when user clicks "Approve"
# =============================================================

APPROVED_QUERIES: set = set()


# =============================================================
# SESSION-LEVEL ACTIVE DB CONFIG STORE
# Stores prompt-based DB switches so they persist across tool
# calls within the same chat session.
# Key: thread_id (session_id)  Value: db_config dict
# =============================================================

_session_db_configs: dict = {}

def get_session_db_config(thread_id: str) -> dict | None:
    return _session_db_configs.get(thread_id)

def set_session_db_config(thread_id: str, db_config: dict):
    _session_db_configs[thread_id] = db_config
    logger.info(f"[Session {thread_id[:8]}...] Active DB switched to: {db_config.get('database')} @ {db_config.get('host')}")

def clear_session_db_config(thread_id: str):
    _session_db_configs.pop(thread_id, None)


# =============================================================
# SECURE CONFIGURATION CONTEXT MANAGER
# =============================================================

@contextmanager
def use_tool_db_config(config):
    """
    Propagate the active database configuration to the connection manager.

    Priority order:
      1. Session-level override (set by connect_to_database / switch_database tool)
      2. Per-request RunnableConfig (set by chat.py for the initially selected DB)
    """
    from db_agent_suite.database.connection import set_thread_db_config, clear_thread_db_config

    db_config = None

    # 1. Check session-level store first (prompt-based switch takes priority)
    thread_id = None
    if config:
        if hasattr(config, "configurable"):
            thread_id = config.configurable.get("thread_id")
        elif isinstance(config, dict):
            thread_id = config.get("configurable", {}).get("thread_id")

    if thread_id:
        db_config = get_session_db_config(thread_id)

    # 2. Fall back to RunnableConfig if no session override
    if not db_config and config:
        if hasattr(config, "configurable"):
            db_config = config.configurable.get("db_config")
        elif isinstance(config, dict):
            db_config = config.get("configurable", {}).get("db_config")

    if db_config:
        logger.info(
            f"Routing query to: {db_config.get('host')}:{db_config.get('port')}/{db_config.get('database')}"
        )
        set_thread_db_config(db_config)
    try:
        yield
    finally:
        if db_config:
            clear_thread_db_config()


def has_permission(config, permission: str) -> bool:
    """Read the caller's immutable per-connection permission from graph config."""
    permissions = {}
    if config:
        if hasattr(config, "configurable"):
            permissions = config.configurable.get("permissions", {})
        elif isinstance(config, dict):
            permissions = config.get("configurable", {}).get("permissions", {})
    return bool(permissions.get(permission, False))


# =============================================================
# TOOLS
# =============================================================

@tool
def list_tables(config: RunnableConfig = None) -> str:
    """
    List all tables available in the connected PostgreSQL database.
    Call this first to understand what data exists before writing any queries.
    """
    if not has_permission(config, "can_read"):
        return "ERROR: You do not have read access to this database."

    query = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_type = 'BASE TABLE';
    """
    with use_tool_db_config(config):
        try:
            with get_db_cursor() as cursor:
                cursor.execute(query)
                tables = cursor.fetchall()
                if not tables:
                    return "No tables found in the public schema."
                return "Tables in the database:\n" + "\n".join([f"- {t[0]}" for t in tables])
        except Exception as e:
            logger.error(f"Error listing tables: {e}")
            return f"Error listing tables: {str(e)}"


@tool
def get_schema(table_name: str, config: RunnableConfig = None) -> str:
    """
    Retrieve the schema (columns, data types, nullability, primary keys,
    and foreign keys) for a specific table.

    Args:
        table_name: The name of the database table to inspect.
    """
    if not has_permission(config, "can_read"):
        return "ERROR: You do not have read access to this database."

    # Sanitize to prevent injection in catalog query
    table_name_clean = re.sub(r"[^a-zA-Z0-9_]", "", table_name)

    column_query = """
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = %s
    ORDER BY ordinal_position;
    """

    key_query = """
    SELECT
        tc.constraint_type,
        kcu.column_name,
        ccu.table_name  AS foreign_table_name,
        ccu.column_name AS foreign_column_name
    FROM
        information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema    = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema    = tc.table_schema
    WHERE tc.table_name = %s;
    """

    with use_tool_db_config(config):
        try:
            with get_db_cursor() as cursor:
                cursor.execute(column_query, (table_name_clean,))
                columns = cursor.fetchall()

                cursor.execute(key_query, (table_name_clean,))
                keys = cursor.fetchall()

                if not columns:
                    return f"Table '{table_name}' does not exist or has no columns."

                schema_info = f"Schema for table '{table_name}':\nColumns:\n"
                for col in columns:
                    null_status = "NULL" if col[2] == "YES" else "NOT NULL"
                    schema_info += f"  - {col[0]} ({col[1]}) {null_status}\n"

                if keys:
                    schema_info += "Constraints:\n"
                    for key in keys:
                        ctype, col_name, ftable, fcol = key
                        if ctype == "PRIMARY KEY":
                            schema_info += f"  - PRIMARY KEY on column: {col_name}\n"
                        elif ctype == "FOREIGN KEY":
                            schema_info += f"  - FOREIGN KEY: {col_name} -> {ftable}({fcol})\n"

                return schema_info
        except Exception as e:
            logger.error(f"Error getting schema for {table_name}: {e}")
            return f"Error retrieving schema: {str(e)}"


@tool
def query_db(sql_query: str, config: RunnableConfig = None) -> str:
    """
    Execute a read-only SELECT SQL query against the database and return results.
    Only SELECT statements are permitted. Never use this for data modifications.

    Args:
        sql_query: A valid PostgreSQL SELECT statement.
    """
    if not has_permission(config, "can_read"):
        return "ERROR: You do not have read access to this database."

    # Safety gate: only allow SELECT
    analysis = analyze_sql_safety(sql_query)
    if not analysis["safe"] or analysis["type"] != "read":
        return (
            f"ERROR: Unsafe query detected. query_db only allows SELECT queries. "
            f"Details: {analysis['message']}"
        )

    with use_tool_db_config(config):
        try:
            with get_db_cursor() as cursor:
                cursor.execute(sql_query)
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    rows = cursor.fetchall()
                    if not rows:
                        return "Query returned 0 rows."
                    res = f"Columns: {', '.join(columns)}\n"
                    res += f"Returned {len(rows)} rows:\n"
                    for r in rows:
                        res += f"- {dict(zip(columns, r))}\n"
                    return res
                else:
                    return "Query executed successfully, but returned no description."
        except Exception as e:
            logger.error(f"Error executing SELECT query: {e}")
            return f"Database Error: {str(e)}"


@tool
def modify_db(sql_query: str, config: RunnableConfig = None) -> str:
    """
    Execute a data-modifying SQL statement (INSERT, UPDATE, DELETE).
    This will pause and ask the user for explicit approval before executing.
    Use create_table for CREATE TABLE statements — do NOT pass CREATE here.

    Args:
        sql_query: A valid PostgreSQL INSERT, UPDATE, or DELETE statement.
    """
    if not has_permission(config, "can_write"):
        return "ERROR: You do not have permission to modify this database."

    # Safety gate: block destructive DDL
    analysis = analyze_sql_safety(sql_query)
    if not analysis["safe"]:
        return f"ERROR: Destructive query blocked. Use create_table tool for CREATE TABLE. Details: {analysis['message']}"

    if analysis["type"] == "read":
        return "ERROR: Use query_db for SELECT queries, not modify_db."

    # Normalize for matching (ignore extra whitespace)
    norm_query = " ".join(sql_query.strip().split())
    approved_normalized = {" ".join(q.strip().split()) for q in APPROVED_QUERIES}

    if norm_query not in approved_normalized:
        logger.info(f"modify_db: interrupting graph for user approval of: {sql_query}")
        approved = interrupt({
            "action": "approve_sql",
            "sql": sql_query,
            "message": "This query will modify the database. Do you want to proceed?"
        })
        if not approved:
            return "Database modification cancelled by user."

    with use_tool_db_config(config):
        try:
            logger.info(f"Executing approved write query: {sql_query}")
            with get_db_cursor(commit=True) as cursor:
                cursor.execute(sql_query)
                rowcount = cursor.rowcount
                return f"SUCCESS: Query executed. Affected rows: {rowcount}"
        except Exception as e:
            logger.error(f"Error executing write query: {e}")
            return f"Database Error during modification: {str(e)}"


@tool
def create_table(sql_query: str, config: RunnableConfig = None) -> str:
    """
    Execute a CREATE TABLE (or ALTER TABLE / DROP TABLE) DDL statement.
    This will pause and ask the user for explicit approval before executing.
    Use this tool whenever the user asks to create, alter, or drop a table.

    Args:
        sql_query: A valid PostgreSQL DDL statement (CREATE TABLE, ALTER TABLE, DROP TABLE, etc.)
    """
    if not has_permission(config, "can_write"):
        return "ERROR: You do not have permission to create or alter tables in this database."

    upper = sql_query.strip().upper()
    allowed_ddl = ("CREATE TABLE", "CREATE INDEX", "ALTER TABLE", "DROP TABLE", "DROP INDEX")
    if not any(upper.startswith(k) for k in allowed_ddl):
        return "ERROR: create_table only accepts CREATE TABLE, ALTER TABLE, DROP TABLE, CREATE INDEX, DROP INDEX statements."

    norm_query = " ".join(sql_query.strip().split())
    approved_normalized = {" ".join(q.strip().split()) for q in APPROVED_QUERIES}

    if norm_query not in approved_normalized:
        logger.info(f"create_table: interrupting graph for user approval of: {sql_query}")
        approved = interrupt({
            "action": "approve_sql",
            "sql": sql_query,
            "message": "This will make a structural change to the database schema. Do you want to proceed?"
        })
        if not approved:
            return "Schema change cancelled by user."

    with use_tool_db_config(config):
        try:
            logger.info(f"Executing approved DDL: {sql_query}")
            with get_db_cursor(commit=True) as cursor:
                cursor.execute(sql_query)
                return f"SUCCESS: DDL executed successfully. Statement: {sql_query[:80]}..."
        except Exception as e:
            logger.error(f"Error executing DDL: {e}")
            return f"Database Error during DDL: {str(e)}"


# =============================================================
# TOOL REGISTRY
# =============================================================

def _get_configurable(config) -> dict:
    """Helper to extract the configurable dict from either a RunnableConfig object or plain dict."""
    if config is None:
        return {}
    if hasattr(config, "configurable"):
        return config.configurable or {}
    if isinstance(config, dict):
        return config.get("configurable", {})
    return {}


def _analyze_new_db(db_config: dict) -> str:
    """
    Connect to a new database and return a rich overview: tables + column/row counts.
    Runs after a connect/switch so the LLM can immediately answer questions.
    """
    import psycopg2
    try:
        conn = psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            dbname=db_config["database"],
            user=db_config["user"],
            password=db_config["password"],
            connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]

        if not tables:
            cur.close(); conn.close()
            return "Connected successfully. No tables found in public schema."

        lines = []
        for t in tables:
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = %s AND table_schema = 'public';
            """, (t,))
            col_count = cur.fetchone()[0]
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}";')
                row_count = cur.fetchone()[0]
            except Exception:
                row_count = "?"
            lines.append(f"  • **{t}** — {col_count} columns, {row_count} rows")

        cur.close(); conn.close()
        return "\n".join(lines)
    except Exception as e:
        return f"Connection test failed: {e}"


@tool
def connect_to_database(connection_name: str, config: RunnableConfig = None) -> str:
    """
    Connect to a specific database by its name. Use this tool when the user says things like
    'connect to X', 'use the X database', or 'I want to work with X database'.

    After connecting, automatically analyses the new database in the background and returns
    a full overview of all tables, column counts, and row counts so you can immediately
    answer questions about the data without extra tool calls.

    Args:
        connection_name: The name or keyword of the database connection to connect to.
    """
    cfg = _get_configurable(config)
    available: list = cfg.get("available_connections", [])
    thread_id: str  = cfg.get("thread_id", "")

    if not available:
        return "No database connections are available for your account. Ask an admin to add one."

    # Fuzzy name match — case-insensitive substring
    name_lower = connection_name.lower().strip()
    match = next(
        (c for c in available if name_lower in c["name"].lower() or c["name"].lower() in name_lower),
        None,
    )

    if not match:
        names = ", ".join(f'"{c["name"]}"' for c in available)
        return (
            f"❌ No database found matching **'{connection_name}'**.\n"
            f"Available databases: {names}"
        )

    if not match.get("usable"):
        return (
            f"❌ Database **'{match['name']}'** exists but its credentials could not be decrypted. "
            f"Please contact your administrator."
        )

    new_config = {
        "host":            match["host"],
        "port":            match["port"],
        "database":        match["database"],
        "user":            match["user"],
        "password":        match["password"],
        "connection_id":   match["id"],
        "connection_name": match["name"],
    }

    # Persist as the session's active db override
    if thread_id:
        set_session_db_config(thread_id, new_config)

    # Background analysis
    overview = _analyze_new_db(new_config)

    return (
        f"✅ **Connected to '{match['name']}'**\n"
        f"Host: `{new_config['host']}` | Database: `{new_config['database']}`\n\n"
        f"**Schema Overview:**\n{overview}\n\n"
        f"I'm now working with **{match['name']}**. You can ask me anything about this database!"
    )


@tool
def switch_database(connection_name: str, config: RunnableConfig = None) -> str:
    """
    Switch the active database connection to a different one mid-conversation.
    Use this when the user says 'switch to X', 'change to X database', or 'now use X'.

    This continues the same chat session without starting a new one.
    """
    return connect_to_database.invoke({"connection_name": connection_name, "config": config})


@tool
def list_available_databases(config: RunnableConfig = None) -> str:
    """
    List all database connections available to the current user.
    Use this when the user asks 'what databases do I have?', 'which databases can I access?',
    or before connecting to remind them of their options.
    """
    cfg = _get_configurable(config)
    available: list = cfg.get("available_connections", [])

    if not available:
        return "No database connections are configured for your account."

    thread_id = cfg.get("thread_id", "")
    active_config = get_session_db_config(thread_id) if thread_id else None
    active_id = active_config.get("connection_id") if active_config else None

    lines = []
    for c in available:
        status = "🟢 **ACTIVE**" if c["id"] == active_id else ("✅ Ready" if c.get("usable") else "❌ Unavailable")
        perms = []
        if c.get("can_read"):  perms.append("read")
        if c.get("can_write"): perms.append("write")
        perm_str = ", ".join(perms) if perms else "none"
        lines.append(f"• **{c['name']}** — {status} | Permissions: {perm_str}")

    return "**Your available databases:**\n" + "\n".join(lines)



@tool
def add_database_connection(
    name: str, host: str, port: int, database: str, user: str, password: str, config: RunnableConfig = None
) -> str:
    """
    Create and save a new database connection when the user provides credentials (host, database, user, password, etc.).
    This adds the database to their list of available connections.

    After calling this tool, you should usually call switch_database to switch to the newly created connection.

    Args:
        name: A recognizable friendly name for the connection (e.g. "Production DB")
        host: Database host (e.g. 192.168.1.100 or db.example.com)
        port: Database port (usually 5432)
        database: Name of the postgres database
        user: Database username
        password: Password for the database user
    """
    cfg = _get_configurable(config)
    user_info = cfg.get("user_info", {})
    if not user_info:
        return "❌ Error: Cannot create connection. User context is missing."

    import psycopg2
    try:
        test_conn = psycopg2.connect(
            host=host, port=port, dbname=database, user=user, password=password, connect_timeout=5
        )
        test_conn.close()
    except Exception as e:
        return f"❌ Could not connect to database with those credentials: {e}"

    from db_agent_suite.database.queries import save_user_connection, set_employee_permission
    from db_agent_suite.database.connection import get_master_db_cursor
    
    if user_info.get("role") != "admin":
        try:
            with get_master_db_cursor() as cursor:
                cursor.execute("SELECT can_add_db FROM auth_users WHERE id = %s;", (user_info["id"],))
                row = cursor.fetchone()
                if not row or not row[0]:
                    return "❌ Error: You do not have permission to add new database connections."
        except Exception as e:
            return f"❌ Database error verifying permissions: {e}"

    conn_id = save_user_connection(
        user_id=user_info["id"],
        name=name,
        conn_config={"host": host, "port": port, "database": database, "user": user, "password": password},
        user_key=user_info.get("user_key", "")
    )

    if not conn_id:
        return "❌ Failed to save the database connection to the system."

    try:
        set_employee_permission(conn_id, user_info["id"], can_read=True, can_write=True, can_create_tables=True)
    except:
        pass

    available = cfg.get("available_connections", [])
    available.append({
        "id": conn_id, "name": name, "host": host, "port": port, "database": database,
        "user": user, "password": password, "usable": True,
        "can_read": True, "can_write": True
    })

    return f"✅ Database connection '{name}' created successfully! You can now use switch_database('{name}') to connect to it."


TOOLS = [
    list_tables,
    get_schema,
    query_db,
    modify_db,
    create_table,
    connect_to_database,
    switch_database,
    list_available_databases,
    add_database_connection,
]
