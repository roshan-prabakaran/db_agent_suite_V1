import os
from pathlib import Path

# Load .env file for local development.
# In production Docker, env vars are injected by the runtime - load_dotenv
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
# LITELLM GATEWAY & DUAL VIRTUAL KEYS
# =============================================================
# Base URL for self-hosted LiteLLM Proxy (e.g. https://litellm.stic.softwareteam.duckdns.org or http://172.16.48.97:4000/v1)
LITELLM_PROXY_BASE_URL = os.getenv(
    "LITELLM_PROXY_BASE_URL", 
    os.getenv("LOCAL_LITELLM_BASE_URL", "")
).rstrip("/")

# Virtual Key 1: For Local Models (Qwen 2.5, Llama Guard 3)
LITELLM_LOCAL_API_KEY = os.getenv(
    "LITELLM_LOCAL_API_KEY", 
    os.getenv("LOCAL_LITELLM_API_KEY", os.getenv("LITELLM_VIRTUAL_KEY_LOCAL", ""))
)

# Virtual Key 2: For Online Models (Groq / OpenAI fallbacks)
LITELLM_ONLINE_API_KEY = os.getenv(
    "LITELLM_ONLINE_API_KEY", 
    os.getenv("ONLINE_LITELLM_API_KEY", os.getenv("LITELLM_VIRTUAL_KEY_ONLINE", ""))
)

# Primary Local Models
LOCAL_GUARDRAIL_MODEL = os.getenv("LOCAL_GUARDRAIL_MODEL", "llama-guard-3-1b")
LOCAL_CHAT_MODEL = os.getenv(
    "LOCAL_CHAT_MODEL", 
    os.getenv("LOCAL_LITELLM_MODEL", "qwen-2.5-7b-instruct")
)

# Online Fallback Models
ONLINE_GUARDRAIL_MODEL = os.getenv("ONLINE_GUARDRAIL_MODEL", "groq/openai/gpt-oss-safeguard-20b")
ONLINE_FALLBACK_MODEL_1 = os.getenv("ONLINE_FALLBACK_MODEL_1", "groq/openai/gpt-oss-120b")
ONLINE_FALLBACK_MODEL_2 = os.getenv("ONLINE_FALLBACK_MODEL_2", "groq/openai/gpt-oss-20b")

# Direct Provider Keys (used as ultimate safety net)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# =============================================================
# LANGFUSE OBSERVABILITY
# =============================================================
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))

# =============================================================
# SECURITY
# =============================================================
HTTPS_SECURE = os.getenv("HTTPS_SECURE", "false").lower() == "true"
