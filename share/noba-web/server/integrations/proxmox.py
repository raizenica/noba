# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Proxmox VE integration (PVEAPIToken auth)."""
from __future__ import annotations

import httpx

from .base import _http_get


# ── Proxmox VE ────────────────────────────────────────────────────────────
def get_proxmox(url: str, user: str, token_name: str, token_value: str,
                verify_ssl: bool = True) -> dict | None:
    if not url or not user or not token_name or not token_value:
        return None
    base      = url.rstrip("/")
    user_full = user if "@" in user else f"{user}@pam"
    # If token_name already contains '!' it's a full token ID (e.g. "root@pam!noba-api"),
    # so use it directly.  Otherwise prepend user_full!.
    token_id  = token_name if "!" in token_name else f"{user_full}!{token_name}"
    auth_hdr  = f"PVEAPIToken={token_id}={token_value}"
    hdrs      = {"Authorization": auth_hdr, "Accept": "application/json"}
    result    = {"nodes": [], "vms": [], "status": "offline"}
    try:
        nodes_data = _http_get(f"{base}/api2/json/nodes", hdrs, timeout=5, verify=verify_ssl).get("data", [])
        for node in nodes_data:
            node_name = node.get("node", "unknown")
            maxmem    = node.get("maxmem", 1) or 1
            result["nodes"].append({
                "name":        node_name,
                "status":      node.get("status", "unknown"),
                "cpu":         round(node.get("cpu", 0) * 100, 1),
                "mem_percent": round(node.get("mem", 0) / maxmem * 100, 1),
            })
            for ep, vtype in (("qemu", "qemu"), ("lxc", "lxc")):
                try:
                    for vm in _http_get(
                        f"{base}/api2/json/nodes/{node_name}/{ep}", hdrs,
                        timeout=4, verify=verify_ssl,
                    ).get("data", [])[:30]:
                        mmem = vm.get("maxmem", 1) or 1
                        result["vms"].append({
                            "vmid":        vm.get("vmid"),
                            "name":        vm.get("name", f"{vtype}-{vm.get('vmid')}"),
                            "type":        vtype,
                            "node":        node_name,
                            "status":      vm.get("status", "unknown"),
                            "cpu":         round(vm.get("cpu", 0) * 100, 1),
                            "mem_percent": round(vm.get("mem", 0) / mmem * 100, 1),
                        })
                except (httpx.HTTPError, KeyError, ValueError):
                    pass
        result["status"] = "online"
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    return result
