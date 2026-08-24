from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from db_agent_suite.api.auth import router as auth_router
from db_agent_suite.api.connections import router as conn_router
from db_agent_suite.api.chat import router as chat_router
from db_agent_suite.api.admin import router as admin_router
from db_agent_suite.api.dashboard import router as dashboard_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

app = FastAPI(title="DB Agent Suite API")

# Configure CORS for local development with Next.js
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(conn_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
