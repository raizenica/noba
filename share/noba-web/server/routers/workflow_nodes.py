# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Router: workflow node catalog endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import workflow_nodes as wn
from ..deps import _get_auth, handle_errors

router = APIRouter()


@router.get("/api/workflow-nodes")
@handle_errors
def list_workflow_nodes(user=Depends(_get_auth)) -> list[dict]:
    """Return all available workflow action node descriptors (built-in + plugin)."""
    return wn.get_node_descriptors()
