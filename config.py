import os
from pathlib import Path

# Load .env file for local development.
# In production Docker, env vars are injected by the runtime — load_dotenv
# is a no-op when variables are already set, so this is safe in both cases.
try:
    from dotenv import load_dotenv
    # Walk up directories to find a .env file relative to this package
    _env_file = Path(__file__).parent / ".env"
    if not _env_file.exists():
        _env_file = Path(__file__).parent.parent / ".env"
    load_dotenv(dotenv_path=str(_env_file), override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on OS environment only


# =============================================================
# MASTER DATABASE (PostgreSQL)
# =============================================================
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

# The secret used to encrypt the saved target database passwords
DB_CONNECTION_ENCRYPTION_SECRET = os.getenv("DB_CONNECTION_ENCRYPTION_SECRET")

# =============================================================
# REDIS CACHE
# =============================================================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# =============================================================
# LLM GATEWAY (Groq / OpenAI)
# =============================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# =============================================================
# LANGFUSE OBSERVABILITY
# =============================================================
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))
