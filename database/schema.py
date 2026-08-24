import logging
from db_agent_suite.database.connection import get_master_db_cursor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DBSchema")

def initialize_database():
    """
    Creates tables if they do not exist and populates them with sample seed data.
    """
    logger.info("Initializing database schemas...")

    create_users_table = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        role VARCHAR(50) NOT NULL,
        status VARCHAR(50) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    create_orders_table = """
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        product VARCHAR(100) NOT NULL,
        amount NUMERIC(10, 2) NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    create_auth_users_table = """
    CREATE TABLE IF NOT EXISTS auth_users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        account_role VARCHAR(20) NOT NULL DEFAULT 'employee'
            CHECK (account_role IN ('admin', 'employee')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    create_db_connections_table = """
    CREATE TABLE IF NOT EXISTS db_connections (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        host VARCHAR(255) NOT NULL,
        port VARCHAR(10) NOT NULL,
        database_name VARCHAR(100) NOT NULL,
        username VARCHAR(100) NOT NULL,
        encrypted_password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    create_history_table = """
    CREATE TABLE IF NOT EXISTS conversation_history (
        id SERIAL PRIMARY KEY,
        session_id VARCHAR(100) NOT NULL,
        user_id INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
        role VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    create_db_connection_permissions_table = """
    CREATE TABLE IF NOT EXISTS db_connection_permissions (
        id SERIAL PRIMARY KEY,
        connection_id INTEGER NOT NULL REFERENCES db_connections(id) ON DELETE CASCADE,
        employee_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
        can_read BOOLEAN NOT NULL DEFAULT FALSE,
        can_write BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (connection_id, employee_id)
    );
    """

    try:
        with get_master_db_cursor(commit=True) as cursor:
            # 1. Create tables
            cursor.execute(create_auth_users_table)
            cursor.execute(create_db_connections_table)
            cursor.execute(create_db_connection_permissions_table)
            cursor.execute(create_users_table)
            cursor.execute(create_orders_table)
            cursor.execute(create_history_table)
            
            # Safe migrations for installations created before RBAC was added.
            try:
                cursor.execute("ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_users(id) ON DELETE CASCADE;")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS account_role VARCHAR(20) NOT NULL DEFAULT 'employee';")
                # Existing installations have no administrator; promote the oldest account once.
                cursor.execute("SELECT COUNT(*) FROM auth_users WHERE account_role = 'admin';")
                if cursor.fetchone()[0] == 0:
                    cursor.execute("UPDATE auth_users SET account_role = 'admin' WHERE id = (SELECT id FROM auth_users ORDER BY id ASC LIMIT 1);")
            except Exception as e:
                logger.warning(f"Could not complete RBAC migration: {e}")
                
            logger.info("Database tables created or verified.")

            # 2. Seed mock users if empty
            cursor.execute("SELECT COUNT(*) FROM users;")
            if cursor.fetchone()[0] == 0:
                logger.info("Seeding users table...")
                users_data = [
                    ("Alice Vance", "alice@example.com", "Admin", "Active"),
                    ("Bob Miller", "bob@example.com", "Editor", "Active"),
                    ("Charlie Smith", "charlie@example.com", "Viewer", "Inactive"),
                    ("Diana Prince", "diana@example.com", "Admin", "Active"),
                    ("Ethan Hunt", "ethan@example.com", "Editor", "Suspended")
                ]
                cursor.executemany(
                    "INSERT INTO users (name, email, role, status) VALUES (%s, %s, %s, %s);",
                    users_data
                )

            # 3. Seed mock orders if empty
            cursor.execute("SELECT COUNT(*) FROM orders;")
            if cursor.fetchone()[0] == 0:
                logger.info("Seeding orders table...")
                # Fetch user IDs
                cursor.execute("SELECT id, name FROM users;")
                user_id_map = {name: uid for uid, name in cursor.fetchall()}
                
                orders_data = [
                    (user_id_map["Alice Vance"], "MacBook Pro", 1999.99),
                    (user_id_map["Alice Vance"], "iPhone 15", 999.00),
                    (user_id_map["Bob Miller"], "Mechanical Keyboard", 150.50),
                    (user_id_map["Charlie Smith"], "Python Book", 45.00),
                    (user_id_map["Diana Prince"], "Noise Cancelling Headphones", 349.99)
                ]
                cursor.executemany(
                    "INSERT INTO orders (user_id, product, amount) VALUES (%s, %s, %s);",
                    orders_data
                )
                
            logger.info("Database seeding completed.")
            return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise e
