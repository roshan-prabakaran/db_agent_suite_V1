import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DBSchema")

# Schema bootstrap removed - all tables already exist in the database.
# No automatic table creation or seeding runs on startup.

def initialize_database():
    """No-op: tables already exist. Nothing to create or seed."""
    logger.info("initialize_database called - skipping, tables already exist.")
    return True
