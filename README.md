# 🤖 Deep DB Agent & LLM Gateway Suite

This is a comprehensive, database-connected AI agent suite built with Streamlit, PostgreSQL, Redis, LiteLLM Gateway, Guardrails, and Langfuse Observability.

---

## 🛠️ API & Connection Keys Setup

Create or update the `.env` file in the root directory with the following variables:

### 1. LLM Gateway Credentials
- **`GROQ_API_KEY`** (Required): Used as the primary and secondary models (`llama-3.1-70b-versatile`, `llama-3.3-70b-specdec`, `llama-3.1-8b-instant`).
- **`OPENAI_API_KEY`** (Optional): Add if you want to route or fall back to OpenAI models (like `gpt-4o-mini`).

### 2. PostgreSQL Connection Details (Required)
The agent operates directly on this database. Configure these to point to your PostgreSQL instance:
- **`POSTGRES_HOST`**: e.g., `localhost` or your remote DB host.
- **`POSTGRES_PORT`**: e.g., `5432`
- **`POSTGRES_DB`**: e.g., `postgres`
- **`POSTGRES_USER`**: e.g., `postgres`
- **`POSTGRES_PASSWORD`**: e.g., `yourpassword`

### 3. Redis Connection (Optional)
- **`REDIS_HOST`**: e.g., `localhost`
- **`REDIS_PORT`**: e.g., `6379`
- **`REDIS_PASSWORD`**: e.g., `yourpassword` (if any)
*Note: If a Redis server is not running or credentials are not specified, the system automatically falls back to an in-memory `fakeredis` mock, ensuring caching still works!*

### 4. Langfuse Observability (Optional)
Configure these to capture traces of your agent's thinking, queries, and LLM usage:
- **`LANGFUSE_PUBLIC_KEY`**: Your Langfuse project public key.
- **`LANGFUSE_SECRET_KEY`**: Your Langfuse project secret key.
- **`LANGFUSE_HOST`**: e.g., `https://cloud.langfuse.com` or `http://localhost:3000` (self-hosted).
*Note: If Langfuse credentials are not provided, tracing is disabled gracefully without throwing errors.*

---

## 🐳 Quick Infrastructure Stack via Docker

If you do not have local instances of PostgreSQL or Redis, run these commands in your shell to spin up containerized instances:

```bash
# Spin up PostgreSQL DB on port 5432
docker run --name agent-postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres

# Spin up Redis cache on port 6379
docker run --name agent-redis -p 6379:6379 -d redis
```

---

## 🚀 How to Run the Suite

### 1. Initialize dependencies
Make sure you are running in the virtual environment. To run with the virtual environment dependencies:
```bash
# Run unit verification tests
.venv\Scripts\python db_agent_suite/run_tests.py
```

### 2. Launch the Streamlit application
```bash
.venv\Scripts\streamlit run db_agent_suite/app.py
```

For production, set `DB_CONNECTION_ENCRYPTION_SECRET` to a long, unique secret.
The first account created is an administrator; all later accounts are employees.
Administrators grant each employee read and approved-write access per database.

---

## 🛡️ Key Features Implemented

1. **LiteLLM Gateway**: Standardized routing between models on Groq and OpenAI. Built-in fallback routes (if primary `70b` model rate-limits or fails, automatically switches to `specdec` or `8b` fallback models).
2. **Fallback Notifications**: Displays a warning alert banner in the Streamlit UI immediately whenever a fallback occurs.
3. **Automatic Cache Connection**: Connects to Redis caching to optimize response speeds and minimize token usage. Automatically falls back to in-memory `fakeredis` offline.
4. **Prompt Injection Guardrails**: A rule-based regex pre-filter combined with a small LLM classification check to block system instruction bypasses and jailbreaks.
5. **PostgreSQL DB Agent**: Interactive SQL tool execution loop. The agent can list tables, get schemas, run read-only `SELECT` queries automatically, and propose data updates (`INSERT/UPDATE/DELETE`).
6. **Interactive Write Approval**: All modifications require manual user approval ("Approve" or "Reject") via Streamlit before committing.
7. **Langfuse Observability**: Trace spans log every agent thought, query parameter, tool execution results, and token metrics.
