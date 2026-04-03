# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""n8n workflow automation integration."""
from __future__ import annotations

import logging

from .base import _http_get

logger = logging.getLogger("noba")


def collect_n8n(base_url: str, api_key: str) -> dict | None:
    """Fetch n8n workflow stats and recent executions."""
    if not base_url or not api_key:
        return None
    hdrs = {"X-N8N-API-KEY": api_key}
    try:
        # Fetch workflows
        wf_data = _http_get(f"{base_url.rstrip('/')}/api/v1/workflows?active=true", hdrs, timeout=8)
        workflows = wf_data.get("data", []) if isinstance(wf_data, dict) else []

        # Fetch recent executions
        ex_data = _http_get(f"{base_url.rstrip('/')}/api/v1/executions?limit=20&status=error,success", hdrs, timeout=8)
        executions = ex_data.get("data", []) if isinstance(ex_data, dict) else []

        total_wf = len(workflows)
        active_wf = sum(1 for w in workflows if w.get("active"))

        total_exec = len(executions)
        failed_exec = sum(1 for e in executions if e.get("status") == "error" or not e.get("finished"))

        last_exec = None
        if executions:
            last_exec = executions[0].get("startedAt") or executions[0].get("createdAt")

        return {
            "status": "online",
            "workflows": total_wf,
            "active_workflows": active_wf,
            "recent_executions": total_exec,
            "failed_executions": failed_exec,
            "failure_rate": round(failed_exec / total_exec * 100, 1) if total_exec else 0,
            "last_execution": last_exec,
            "workflow_names": [w.get("name", "") for w in workflows[:10]],
        }
    except Exception as e:
        logger.debug("n8n collection failed: %s", e)
        return {"status": "error", "error": str(e)}
