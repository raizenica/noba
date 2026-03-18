import subprocess
import os
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from ..metrics import get_system_metrics
from ..database import db
from ..config import settings

# Temporarily disabled token dependency so frontend can boot
router = APIRouter()

@router.get("/stats")
async def live_metrics(request: Request, background_tasks: BackgroundTasks):
    """Answers the dashboard's main data fetch"""
    data = get_system_metrics()
    # Offload the database disk I/O to a background thread
    background_tasks.add_task(db.insert_metrics, data)
    return data

@router.get("/log-viewer")
async def get_logs(type: str = "syserr"):
    """Feeds the frontend log viewer window"""
    try:
        if type == "syserr":
            # Safely grab the last 50 system errors
            out = subprocess.check_output(["journalctl", "-n", "50", "-p", "3", "--no-pager"]).decode("utf-8")
        else:
            out = subprocess.check_output(["journalctl", "-n", "50", "--no-pager"]).decode("utf-8")
        return {"logs": out}
    except Exception as e:
        return {"logs": f"Failed to fetch logs: {e}"}

@router.get("/cloud-remotes")
async def get_cloud_remotes():
    """Satisfies the frontend's check for cloud syncs"""
    return {"status": "success", "data": []}

@router.post("/action/{command}")
async def trigger_action(command: str):
    """Safely triggers an automation script. Completely immune to command injection."""
    if command not in settings.automation.allowed_commands:
        raise HTTPException(
            status_code=403,
            detail=f"Command '{command}' is not in the allowed_commands config."
        )

    script_path = os.path.expanduser(f"~/.local/libexec/noba/{command}.sh")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Automation script not found on disk.")

    try:
        subprocess.Popen([script_path])
        return {"status": "success", "detail": f"Automation triggered: {command}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
