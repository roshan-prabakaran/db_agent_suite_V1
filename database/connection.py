"""
connection.py

Manages thread-safe PostgreSQL connection pools dynamically.
Supports thread-local overrides for the active target database and
defaults to environment variables.

"""

import logging
import threading
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from db_agent_suite import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DBConnection")

# Thread-local storage for programmatic overrides (e.g. per-request target DB from the agent)
_thread_local = threading.local()
print(_thread_local)
# Dictionary mapping cache keys to psycopg2 connection pools
_connection_pools = {}
_pools_lock = threading.Lock()


def set_thread_db_config(config: dict):
    """
    Set database connection parameters for the current thread.
    Used by tools to route queries to the user's selected target database.
    """
    _thread_local.db_config = config


def clear_thread_db_config():
    """
    Clear database connection parameters for the current thread.
    """
    if hasattr(_thread_local, "db_config"):
        del _thread_local.db_config


def get_current_db_config() -> dict:
    """
    Resolve the active database connection credentials.
    Priority:
      1. Thread-local override (set by agent tools for the selected target DB)
      2. Environment variables (fallback / master DB)
    """
    # 1. Thread-local override (set by agent tools)
    if hasattr(_thread_local, "db_config") and _thread_local.db_config:
        return _thread_local.db_config

    # 2. Fallback to Environment Variables
    return {
        "host": config.POSTGRES_HOST,
        "port": config.POSTGRES_PORT,
        "database": config.POSTGRES_DB,
        "user": config.POSTGRES_USER,
        "password": config.POSTGRES_PASSWORD,
    }



def get_master_db_config() -> dict:
    """Return the application database configuration, never a selected target DB."""
    return {
        "host": config.POSTGRES_HOST,
        "port": config.POSTGRES_PORT,
        "database": config.POSTGRES_DB,
        "user": config.POSTGRES_USER,
        "password": config.POSTGRES_PASSWORD,
    }



def get_connection_pool():
    """
    Get or create the connection pool for the currently active database config.
    """
    global _connection_pools
    config = get_current_db_config()
    
    # Generate a cache key
    key = f"{config.get('host')}:{config.get('port')}:{config.get('database')}:{config.get('user')}"

    with _pools_lock:
        if key not in _connection_pools:
            try:
                logger.info(f"Initializing connection pool for {config.get('host')}:{config.get('port')}/{config.get('database')} (user: {config.get('user')})")
                _connection_pools[key] = psycopg2.pool.SimpleConnectionPool(
                    1, 10,
                    host=config.get("host"),
                    port=config.get("port"),
                    database=config.get("database"),
                    user=config.get("user"),
                    password=config.get("password")
                )
            except Exception as e:
                logger.error(f"Failed to initialize pool for key {key}: {e}")
                raise ConnectionError(
                    f"Could not connect to PostgreSQL database '{config.get('database')}' on {config.get('host')}:{config.get('port')}.\n"
                    f"Error details: {e}"
                )
        return _connection_pools[key]


@contextmanager
def get_db_connection():
    pool_obj = get_connection_pool()
    conn = pool_obj.getconn()
    try:
        yield conn
    finally:
        try:
            pool_obj.putconn(conn)
        except Exception:
            pass


@contextmanager
def get_db_cursor(commit=False):
    """
    Context manager to obtain a cursor. Auto-closes the cursor.
    Optionally commits the transaction on success.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
            raise e
        finally:
            cursor.close()


@contextmanager
def get_master_db_cursor(commit=False):

    """Cursor for accounts, permissions, and chat history stored in the suite DB."""

    previous = getattr(_thread_local, "db_config", None)
    set_thread_db_config(get_master_db_config())
    try:
        with get_db_cursor(commit=commit) as cursor:
            yield cursor
    finally:
        if previous:
            set_thread_db_config(previous)
        else:
            clear_thread_db_config()

def test_connection(config: dict = None):
    """
    Test connectivity to a PostgreSQL database.
    If config is provided, tests those specific credentials.
    Otherwise, tests the currently active config.
    """
    target_config = config if config is not None else get_current_db_config()
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            host=target_config.get("host"),
            port=target_config.get("port"),
            database=target_config.get("database"),
            user=target_config.get("user"),
            password=target_config.get("password"),
            connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        return True, f"Connected successfully. PostgreSQL version: {version[0]}"
    except Exception as e:
        return False, str(e)
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
