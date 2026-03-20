"""Noba – API router package."""
from __future__ import annotations

from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .automations import router as automations_router
from .integrations import router as integrations_router
from .stats import router as stats_router
from .system import router as system_router

api_router = APIRouter()
api_router.include_router(stats_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(automations_router)
api_router.include_router(integrations_router)
api_router.include_router(system_router)
