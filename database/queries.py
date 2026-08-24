# Queries logic extracted from app.py
import logging
from db_agent_suite import config
from db_agent_suite.database.connection import get_master_db_cursor
from db_agent_suite.utils.security import hash_password, derive_encryption_key, encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

def get_user_by_email(email: str):
    try:
        with get_master_db_cursor() as cursor:
            cursor.execute("SELECT id, email, password_hash, account_role FROM auth_users WHERE email = %s;", (email,))
            row = cursor.fetchone()
            if row:
                return {"id": row[0], "email": row[1], "password_hash": row[2], "role": row[3]}
    except Exception as e:
        logger.error(f"Database query error: {e}")
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
        logger.error(f"Failed to register user: {e}")
    return None

def get_connection_cipher_key() -> str:
    secret = config.DB_CONNECTION_ENCRYPTION_SECRET
    if not secret:
        secret = config.POSTGRES_PASSWORD
    return derive_encryption_key(secret, "db-agent-suite:connection-credentials:v1")

def migrate_connection_password(connection_id: int, password: str):
    with get_master_db_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE db_connections SET encrypted_password = %s WHERE id = %s;",
            (encrypt_data(password, get_connection_cipher_key()), connection_id),
        )

def load_user_connections(user_id: int, user_key: str, role: str):
    try:
        with get_master_db_cursor() as cursor:
            if role == "admin":
                cursor.execute(
                    "SELECT id, name, host, port, database_name, username, encrypted_password, TRUE, TRUE, NULL FROM db_connections WHERE user_id = %s ORDER BY name;",
                    (user_id,)
                )
            else:
                # Employees see connections that admin has shared with them via permissions
                cursor.execute("""
                    SELECT c.id, c.name, c.host, c.port, c.database_name, c.username,
                           c.encrypted_password, p.can_read, p.can_write,
                           CASE WHEN column_exists.yes THEN p.allowed_tables ELSE NULL END
                    FROM db_connections c
                    JOIN db_connection_permissions p ON p.connection_id = c.id
                    CROSS JOIN (
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='db_connection_permissions' AND column_name='allowed_tables'
                        ) AS yes
                    ) AS column_exists
                    WHERE p.employee_id = %s AND (p.can_read = TRUE OR p.can_write = TRUE)
                    ORDER BY c.name;
                """, (user_id,))
            rows = cursor.fetchall()
            connections = []
            cipher_key = get_connection_cipher_key()
            for r in rows:
                dec_pass = ""
                try:
                    dec_pass = decrypt_data(r[6], cipher_key)
                except Exception:
                    # Fallback: try user's raw password as key (legacy support)
                    try:
                        dec_pass = decrypt_data(r[6], user_key)
                        # Migrate to global key
                        migrate_connection_password(r[0], dec_pass)
                        logger.info(f"Migrated connection {r[0]} to global cipher key")
                    except Exception as e2:
                        logger.warning(f"Could not decrypt connection {r[0]}: {e2}")
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
                    "can_read": bool(r[7]),
                    "can_write": bool(r[8]),
                    "allowed_tables": list(r[9]) if r[9] else None,
                })
            return connections
    except Exception as e:
        logger.error(f"Failed to load saved connections: {e}")
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
        logger.error(f"Failed to save connection: {e}")
    return None

def delete_user_connection(conn_id: int, user_id: int):
    try:
        with get_master_db_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM db_connections WHERE id = %s AND user_id = %s;", (conn_id, user_id))
            return True
    except Exception as e:
        logger.error(f"Failed to delete connection: {e}")
    return False

def get_employees():
    with get_master_db_cursor() as cursor:
        cursor.execute("SELECT id, email FROM auth_users WHERE account_role = 'employee' ORDER BY email;")
        return cursor.fetchall()

def set_employee_permission(connection_id: int, employee_id: int, can_read: bool, can_write: bool, allowed_tables=None, can_create_tables: bool = False):
    with get_master_db_cursor(commit=True) as cursor:
        cursor.execute("ALTER TABLE db_connection_permissions ADD COLUMN IF NOT EXISTS allowed_tables TEXT[] DEFAULT NULL;")
        cursor.execute("ALTER TABLE db_connection_permissions ADD COLUMN IF NOT EXISTS can_create_tables BOOLEAN DEFAULT FALSE;")
        cursor.execute("""
            INSERT INTO db_connection_permissions (connection_id, employee_id, can_read, can_write, allowed_tables, can_create_tables)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (connection_id, employee_id)
            DO UPDATE SET can_read = EXCLUDED.can_read, can_write = EXCLUDED.can_write,
                          allowed_tables = EXCLUDED.allowed_tables, can_create_tables = EXCLUDED.can_create_tables;
        """, (connection_id, employee_id, can_read, can_write, allowed_tables, can_create_tables))


