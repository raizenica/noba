"""Router: workflow node catalog endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import _get_auth
from .. import workflow_nodes as wn

router = APIRouter()


@router.get("/api/workflow-nodes")
def list_workflow_nodes(user=Depends(_get_auth)) -> list[dict]:
    """Return all available workflow action node descriptors (built-in + plugin)."""
    return wn.get_node_descriptors()
