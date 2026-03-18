# share/noba-web/server/main.py
import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import settings

# Enterprise Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("noba-server")

app = FastAPI(
    title="NOBA Command Center",
    description="Enterprise SRE Observability and Automation API",
    version="3.3.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to local subnet in strict production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Circuit Breaker / Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled system exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "type": str(type(exc).__name__)}
    )

@app.get("/api/health")
async def health_check():
    """Unauthenticated healthcheck for external monitors (like Uptime Kuma)"""
    return {"status": "healthy", "version": app.version}

# -------------------------------------------------------------------
# Router Mounting (To be added in Phase 3)
# -------------------------------------------------------------------
from .routers import api, auth
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(api.router, prefix="/api", tags=["System"])

# -------------------------------------------------------------------
# Static Frontend Mounting
# -------------------------------------------------------------------
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# This dynamically gets the absolute, unbreakable path to share/noba-web/
BASE_DIR = Path(__file__).resolve().parent.parent

if BASE_DIR.exists():
    app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="web")
else:
    logger.error(f"FATAL: Could not find web directory at {BASE_DIR}")
