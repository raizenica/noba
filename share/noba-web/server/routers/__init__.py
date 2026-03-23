"""Noba – API router package."""
from __future__ import annotations

from fastapi import APIRouter

from .admin import router as admin_router
from .agents import router as agents_router
from .auth import router as auth_router
from .automations import router as automations_router
from .containers import router as containers_router
from .dashboards import router as dashboards_router
from .infrastructure import router as infrastructure_router
from .integration_instances import router as integration_instances_router
from .integrations import router as integrations_router
from .intelligence import router as intelligence_router
from .monitoring import router as monitoring_router
from .operations import router as operations_router
from .security import router as security_router
from .healing import router as healing_router
from .stats import router as stats_router

api_router = APIRouter()
api_router.include_router(stats_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(automations_router)
api_router.include_router(integration_instances_router)
api_router.include_router(integrations_router)
api_router.include_router(agents_router)
api_router.include_router(containers_router)
api_router.include_router(monitoring_router)
api_router.include_router(infrastructure_router)
api_router.include_router(security_router)
api_router.include_router(intelligence_router)
api_router.include_router(operations_router)
api_router.include_router(dashboards_router)
api_router.include_router(healing_router)
