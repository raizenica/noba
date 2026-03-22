"""Noba -- Universal integration heal registry.

Maps abstract heal operations to platform-specific handler configs.
The healing pipeline speaks abstract operations (e.g. 'nas_scrub'),
and this registry resolves them to platform-specific API calls.
"""
from __future__ import annotations

import threading

# {operation_name: {platform_name: handler_config}}
INTEGRATION_HANDLERS: dict[str, dict[str, dict]] = {}

# {category_name: [operation_names]}
OPERATION_CATEGORIES: dict[str, list[str]] = {}

_lock = threading.Lock()


def _register_category(category: str, operations: dict[str, dict[str, dict]]) -> None:
    """Register all operations for a category. Called at module load."""
    op_names = []
    for op_name, platforms in operations.items():
        INTEGRATION_HANDLERS[op_name] = platforms
        op_names.append(op_name)
    OPERATION_CATEGORIES[category] = op_names


def get_integration_handler(operation: str, platform: str) -> dict | None:
    """Get handler config for an operation on a specific platform."""
    return INTEGRATION_HANDLERS.get(operation, {}).get(platform)


def list_operations(category: str) -> list[str]:
    """List all operation names for a category."""
    return OPERATION_CATEGORIES.get(category, [])


def list_platforms(operation: str) -> list[str]:
    """List all platforms that support an operation."""
    return list(INTEGRATION_HANDLERS.get(operation, {}).keys())


def list_categories() -> list[str]:
    """List all registered categories."""
    return list(OPERATION_CATEGORIES.keys())


def register_handler(operation: str, platform: str, config: dict) -> None:
    """Register a plugin handler for a platform. Thread-safe."""
    with _lock:
        if operation not in INTEGRATION_HANDLERS:
            INTEGRATION_HANDLERS[operation] = {}
        INTEGRATION_HANDLERS[operation][platform] = config


# ── Category registrations ──────────────────────────────────────────

# Handler configs are declarative: {method, endpoint, auth}
# Actual execution happens in the executor (Phase 2+).
# "exec" method means run via agent command, not HTTP API.

_register_category("nas", {
    "nas_pool_repair": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/pool/id/{pool}/repair", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Storage.Volume/v1?method=repair", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/disk/disk_manage.cgi?func=repair", "auth": "session"},
        "omv": {"method": "rpc", "service": "FileSystemMgmt", "method_name": "repair", "auth": "session"},
        "unraid": {"method": "exec", "command": "mdcmd check", "auth": "local"},
    },
    "nas_scrub": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/pool/id/{pool}/scrub", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Storage.Volume/v1?method=scrub", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/disk/disk_manage.cgi?func=scrub", "auth": "session"},
        "omv": {"method": "rpc", "service": "FileSystemMgmt", "method_name": "scrub", "auth": "session"},
        "unraid": {"method": "exec", "command": "btrfs scrub start /mnt/disk{n}", "auth": "local"},
    },
    "nas_replication_sync": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/replication/id/{id}/run", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.ReplicationService.Task/v1?method=trigger_run", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/replication/replication.cgi?func=run", "auth": "session"},
        "omv": {"method": "rpc", "service": "ReplicationMgmt", "method_name": "execute", "auth": "session"},
        "unraid": {"method": "exec", "command": "rsync -av /mnt/user/ /mnt/backup/", "auth": "local"},
    },
    "nas_snapshot_create": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/zfs/snapshot", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Core.Share.Snapshot/v1?method=create", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/snapshot/snapshot.cgi?func=create", "auth": "session"},
        "omv": {"method": "rpc", "service": "SnapMgmt", "method_name": "createSnapshot", "auth": "session"},
        "unraid": {"method": "exec", "command": "btrfs subvolume snapshot /mnt/user /mnt/snapshots/snap-$(date +%s)", "auth": "local"},
    },
    "nas_snapshot_rollback": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/zfs/snapshot/id/{id}/rollback", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Core.Share.Snapshot/v1?method=clone", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/snapshot/snapshot.cgi?func=rollback", "auth": "session"},
        "omv": {"method": "rpc", "service": "SnapMgmt", "method_name": "rollbackSnapshot", "auth": "session"},
        "unraid": {"method": "exec", "command": "btrfs subvolume snapshot /mnt/snapshots/{snap} /mnt/user", "auth": "local"},
    },
    "nas_share_restart": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/service/restart", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Core.Service/v1?method=restart", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/services/services.cgi?func=restart&name=smbd", "auth": "session"},
        "omv": {"method": "exec", "command": "systemctl restart smbd nmbd", "auth": "local"},
        "unraid": {"method": "exec", "command": "/etc/rc.d/rc.samba restart", "auth": "local"},
    },
    "nas_cache_clear": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/pool/id/{pool}/cache/flush", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Core.Cache/v1?method=flush", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/disk/disk_manage.cgi?func=flush_cache", "auth": "session"},
        "omv": {"method": "exec", "command": "echo 3 > /proc/sys/vm/drop_caches", "auth": "local"},
        "unraid": {"method": "exec", "command": "echo 3 > /proc/sys/vm/drop_caches", "auth": "local"},
    },
    "nas_quota_enforce": {
        "truenas": {"method": "POST", "endpoint": "/api/v2.0/pool/dataset/id/{id}/quota", "auth": "bearer"},
        "synology": {"method": "POST", "endpoint": "/webapi/SYNO.Core.QuotaStatus/v1?method=set", "auth": "session"},
        "qnap": {"method": "POST", "endpoint": "/cgi-bin/disk/quota.cgi?func=enforce", "auth": "session"},
        "omv": {"method": "rpc", "service": "QuotaMgmt", "method_name": "enforceQuota", "auth": "session"},
        "unraid": {"method": "exec", "command": "quotaon -a", "auth": "local"},
    },
})

_register_category("hypervisor", {
    "vm_restart": {
        "proxmox": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/qemu/{vmid}/status/reboot", "auth": "bearer"},
        "vmware": {"method": "POST", "endpoint": "/rest/vcenter/vm/{vm}/power/reset", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Restart-VM -Name '{vm}' -Force", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "VM", "method_name": "clean_reboot", "auth": "session"},
    },
    "vm_migrate": {
        "proxmox": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/qemu/{vmid}/migrate", "auth": "bearer"},
        "vmware": {"method": "POST", "endpoint": "/rest/vcenter/vm/{vm}/relocate", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Move-VM -Name '{vm}' -DestinationHost '{host}'", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "VM", "method_name": "pool_migrate", "auth": "session"},
    },
    "vm_snapshot": {
        "proxmox": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/qemu/{vmid}/snapshot", "auth": "bearer"},
        "vmware": {"method": "POST", "endpoint": "/rest/vcenter/vm/{vm}/snapshot", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Checkpoint-VM -Name '{vm}'", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "VM", "method_name": "snapshot", "auth": "session"},
    },
    "vm_snapshot_rollback": {
        "proxmox": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/qemu/{vmid}/snapshot/{snap}/rollback", "auth": "bearer"},
        "vmware": {"method": "POST", "endpoint": "/rest/vcenter/vm/{vm}/snapshot/{snap}/revert", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Restore-VMCheckpoint -Name '{snap}' -VMName '{vm}'", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "VM", "method_name": "snapshot_revert", "auth": "session"},
    },
    "vm_resource_adjust": {
        "proxmox": {"method": "PUT", "endpoint": "/api2/json/nodes/{node}/qemu/{vmid}/config", "auth": "bearer"},
        "vmware": {"method": "PATCH", "endpoint": "/rest/vcenter/vm/{vm}/hardware/cpu", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Set-VM -Name '{vm}' -MemoryStartupBytes {mem}", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "VM", "method_name": "set_memory_limits", "auth": "session"},
    },
    "vm_console_reset": {
        "proxmox": {"method": "DELETE", "endpoint": "/api2/json/nodes/{node}/qemu/{vmid}/vncproxy", "auth": "bearer"},
        "vmware": {"method": "POST", "endpoint": "/rest/vcenter/vm/{vm}/console/credentials", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Get-VMConnectAccess -VMName '{vm}' | Remove-VMConnectAccess", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "Console", "method_name": "reset_session", "auth": "session"},
    },
    "hypervisor_maintenance_mode": {
        "proxmox": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/startall", "auth": "bearer"},
        "vmware": {"method": "POST", "endpoint": "/rest/vcenter/host/{host}/maintenance", "auth": "session"},
        "hyperv": {"method": "exec", "command": "Suspend-ClusterNode -Name '{node}'", "auth": "local"},
        "xcpng": {"method": "rpc", "service": "Host", "method_name": "disable", "auth": "session"},
    },
})

_register_category("container_runtime", {
    "container_restart": {
        "docker": {"method": "POST", "endpoint": "/containers/{id}/restart", "auth": "local"},
        "podman": {"method": "POST", "endpoint": "/v4.0.0/libpod/containers/{id}/restart", "auth": "local"},
        "kubernetes": {"method": "POST", "endpoint": "/api/v1/namespaces/{ns}/pods/{pod}/eviction", "auth": "bearer"},
        "lxd": {"method": "PUT", "endpoint": "/1.0/containers/{name}/state", "auth": "local"},
    },
    "container_recreate": {
        "docker": {"method": "exec", "command": "docker rm -f {name} && docker run {args} {image}", "auth": "local"},
        "podman": {"method": "exec", "command": "podman rm -f {name} && podman run {args} {image}", "auth": "local"},
        "kubernetes": {"method": "DELETE", "endpoint": "/api/v1/namespaces/{ns}/pods/{pod}", "auth": "bearer"},
        "lxd": {"method": "exec", "command": "lxc delete --force {name} && lxc launch {image} {name}", "auth": "local"},
    },
    "container_scale": {
        "docker": {"method": "exec", "command": "docker service scale {service}={replicas}", "auth": "local"},
        "podman": {"method": "exec", "command": "podman pod start {pod}", "auth": "local"},
        "kubernetes": {"method": "PATCH", "endpoint": "/apis/apps/v1/namespaces/{ns}/deployments/{name}/scale", "auth": "bearer"},
        "lxd": {"method": "POST", "endpoint": "/1.0/containers", "auth": "local"},
    },
    "container_image_pull": {
        "docker": {"method": "POST", "endpoint": "/images/create?fromImage={image}", "auth": "local"},
        "podman": {"method": "POST", "endpoint": "/v4.0.0/libpod/images/pull", "auth": "local"},
        "kubernetes": {"method": "exec", "command": "kubectl set image deployment/{name} *={image}", "auth": "bearer"},
        "lxd": {"method": "POST", "endpoint": "/1.0/images", "auth": "local"},
    },
    "container_rollback_image": {
        "docker": {"method": "exec", "command": "docker service update --image {prev_image} {service}", "auth": "local"},
        "podman": {"method": "exec", "command": "podman update --image={prev_image} {name}", "auth": "local"},
        "kubernetes": {"method": "POST", "endpoint": "/apis/apps/v1/namespaces/{ns}/deployments/{name}/rollback", "auth": "bearer"},
        "lxd": {"method": "exec", "command": "lxc config set {name} image.description {prev_image}", "auth": "local"},
    },
    "container_network_reconnect": {
        "docker": {"method": "POST", "endpoint": "/networks/{net}/connect", "auth": "local"},
        "podman": {"method": "exec", "command": "podman network connect {net} {name}", "auth": "local"},
        "kubernetes": {"method": "PATCH", "endpoint": "/api/v1/namespaces/{ns}/pods/{pod}", "auth": "bearer"},
        "lxd": {"method": "PATCH", "endpoint": "/1.0/containers/{name}", "auth": "local"},
    },
})

_register_category("reverse_proxy", {
    "proxy_reload_config": {
        "traefik": {"method": "exec", "command": "kill -HUP $(pidof traefik)", "auth": "local"},
        "npm": {"method": "POST", "endpoint": "/api/nginx/redeploy", "auth": "bearer"},
        "caddy": {"method": "POST", "endpoint": "/load", "auth": "bearer"},
        "haproxy": {"method": "exec", "command": "haproxy -f /etc/haproxy/haproxy.cfg -p /run/haproxy.pid -sf $(cat /run/haproxy.pid)", "auth": "local"},
        "nginx": {"method": "exec", "command": "nginx -s reload", "auth": "local"},
    },
    "proxy_upstream_health_reset": {
        "traefik": {"method": "DELETE", "endpoint": "/api/http/services/{service}/health", "auth": "bearer"},
        "npm": {"method": "POST", "endpoint": "/api/nginx/proxy-hosts/{id}/enable", "auth": "bearer"},
        "caddy": {"method": "POST", "endpoint": "/reverse_proxy/upstreams/{name}/reset", "auth": "bearer"},
        "haproxy": {"method": "exec", "command": "echo 'set server {backend}/{server} state ready' | socat stdio /run/haproxy/admin.sock", "auth": "local"},
        "nginx": {"method": "exec", "command": "nginx -s reload", "auth": "local"},
    },
    "proxy_cert_reload": {
        "traefik": {"method": "exec", "command": "kill -USR1 $(pidof traefik)", "auth": "local"},
        "npm": {"method": "POST", "endpoint": "/api/ssl-certificates/{id}/renew", "auth": "bearer"},
        "caddy": {"method": "POST", "endpoint": "/certificates/renew", "auth": "bearer"},
        "haproxy": {"method": "exec", "command": "haproxy -f /etc/haproxy/haproxy.cfg -sf $(cat /run/haproxy.pid)", "auth": "local"},
        "nginx": {"method": "exec", "command": "nginx -s reload", "auth": "local"},
    },
    "proxy_backend_drain": {
        "traefik": {"method": "PATCH", "endpoint": "/api/http/services/{service}", "auth": "bearer"},
        "npm": {"method": "PUT", "endpoint": "/api/nginx/proxy-hosts/{id}", "auth": "bearer"},
        "caddy": {"method": "PATCH", "endpoint": "/reverse_proxy/upstreams/{name}", "auth": "bearer"},
        "haproxy": {"method": "exec", "command": "echo 'set server {backend}/{server} state drain' | socat stdio /run/haproxy/admin.sock", "auth": "local"},
        "nginx": {"method": "exec", "command": "nginx -s quit", "auth": "local"},
    },
    "proxy_cache_purge": {
        "traefik": {"method": "DELETE", "endpoint": "/api/cache", "auth": "bearer"},
        "npm": {"method": "DELETE", "endpoint": "/api/nginx/cache", "auth": "bearer"},
        "caddy": {"method": "DELETE", "endpoint": "/cache", "auth": "bearer"},
        "haproxy": {"method": "exec", "command": "echo 'clear cache' | socat stdio /run/haproxy/admin.sock", "auth": "local"},
        "nginx": {"method": "exec", "command": "rm -rf /var/cache/nginx/*", "auth": "local"},
    },
})

_register_category("dns", {
    "dns_cache_flush": {
        "pihole": {"method": "POST", "endpoint": "/api/dns/flush", "auth": "bearer"},
        "adguard": {"method": "POST", "endpoint": "/control/cache_clear", "auth": "session"},
        "coredns": {"method": "exec", "command": "kill -USR1 $(pidof coredns)", "auth": "local"},
        "unbound": {"method": "exec", "command": "unbound-control flush_zone .", "auth": "local"},
        "bind9": {"method": "exec", "command": "rndc flush", "auth": "local"},
        "technitium": {"method": "DELETE", "endpoint": "/api/cache/flush", "auth": "bearer"},
    },
    "dns_blocklist_update": {
        "pihole": {"method": "POST", "endpoint": "/api/lists/update", "auth": "bearer"},
        "adguard": {"method": "POST", "endpoint": "/control/filtering/refresh", "auth": "session"},
        "coredns": {"method": "exec", "command": "curl -sO https://blocklist.url/list.txt && kill -HUP $(pidof coredns)", "auth": "local"},
        "unbound": {"method": "exec", "command": "unbound-control reload", "auth": "local"},
        "bind9": {"method": "exec", "command": "rndc reconfig", "auth": "local"},
        "technitium": {"method": "POST", "endpoint": "/api/blocklist/forcedUpdate", "auth": "bearer"},
    },
    "dns_upstream_failover": {
        "pihole": {"method": "POST", "endpoint": "/api/config/dns", "auth": "bearer"},
        "adguard": {"method": "PUT", "endpoint": "/control/dns_config", "auth": "session"},
        "coredns": {"method": "exec", "command": "coredns -conf /etc/coredns/Corefile.failover", "auth": "local"},
        "unbound": {"method": "exec", "command": "unbound-control set_option forward-addr: {upstream}", "auth": "local"},
        "bind9": {"method": "exec", "command": "rndc reload", "auth": "local"},
        "technitium": {"method": "POST", "endpoint": "/api/settings/forwarders", "auth": "bearer"},
    },
    "dns_zone_reload": {
        "pihole": {"method": "exec", "command": "pihole restartdns reload", "auth": "local"},
        "adguard": {"method": "POST", "endpoint": "/control/filtering/set_rules", "auth": "session"},
        "coredns": {"method": "exec", "command": "kill -HUP $(pidof coredns)", "auth": "local"},
        "unbound": {"method": "exec", "command": "unbound-control reload", "auth": "local"},
        "bind9": {"method": "exec", "command": "rndc reload {zone}", "auth": "local"},
        "technitium": {"method": "POST", "endpoint": "/api/zones/reload", "auth": "bearer"},
    },
    "dns_forwarder_switch": {
        "pihole": {"method": "POST", "endpoint": "/api/config/dns/upstreams", "auth": "bearer"},
        "adguard": {"method": "PUT", "endpoint": "/control/dns_config", "auth": "session"},
        "coredns": {"method": "exec", "command": "sed -i 's/forward .*/forward . {new_upstream}/' /etc/coredns/Corefile && kill -HUP $(pidof coredns)", "auth": "local"},
        "unbound": {"method": "exec", "command": "unbound-control forward {new_upstream}", "auth": "local"},
        "bind9": {"method": "exec", "command": "rndc reload", "auth": "local"},
        "technitium": {"method": "PUT", "endpoint": "/api/settings/forwarder", "auth": "bearer"},
    },
    "dns_service_restart": {
        "pihole": {"method": "exec", "command": "pihole restartdns", "auth": "local"},
        "adguard": {"method": "POST", "endpoint": "/control/restart", "auth": "session"},
        "coredns": {"method": "exec", "command": "systemctl restart coredns", "auth": "local"},
        "unbound": {"method": "exec", "command": "systemctl restart unbound", "auth": "local"},
        "bind9": {"method": "exec", "command": "systemctl restart named", "auth": "local"},
        "technitium": {"method": "exec", "command": "systemctl restart technitium-dns-server", "auth": "local"},
    },
})

_register_category("media", {
    "media_library_scan": {
        "plex": {"method": "GET", "endpoint": "/library/sections/{section}/refresh", "auth": "token"},
        "jellyfin": {"method": "POST", "endpoint": "/Library/Refresh", "auth": "bearer"},
        "emby": {"method": "POST", "endpoint": "/Library/Refresh", "auth": "bearer"},
        "navidrome": {"method": "POST", "endpoint": "/api/scanner/trigger", "auth": "bearer"},
    },
    "media_db_optimize": {
        "plex": {"method": "PUT", "endpoint": "/library/optimize", "auth": "token"},
        "jellyfin": {"method": "POST", "endpoint": "/System/MediaEncoder/Path", "auth": "bearer"},
        "emby": {"method": "POST", "endpoint": "/System/OptimizeDatabase", "auth": "bearer"},
        "navidrome": {"method": "exec", "command": "navidrome --vacuum", "auth": "local"},
    },
    "media_cache_clear": {
        "plex": {"method": "PUT", "endpoint": "/system/bundles/empty", "auth": "token"},
        "jellyfin": {"method": "DELETE", "endpoint": "/Cache/Images", "auth": "bearer"},
        "emby": {"method": "POST", "endpoint": "/System/Cache/Clean", "auth": "bearer"},
        "navidrome": {"method": "exec", "command": "rm -rf /var/cache/navidrome/*", "auth": "local"},
    },
    "media_transcode_kill": {
        "plex": {"method": "DELETE", "endpoint": "/transcode/sessions/{session}", "auth": "token"},
        "jellyfin": {"method": "DELETE", "endpoint": "/Videos/ActiveEncodings/{deviceId}", "auth": "bearer"},
        "emby": {"method": "DELETE", "endpoint": "/Sessions/{sessionId}/Playing/Stop", "auth": "bearer"},
        "navidrome": {"method": "exec", "command": "pkill -f 'ffmpeg.*navidrome'", "auth": "local"},
    },
    "media_session_terminate": {
        "plex": {"method": "GET", "endpoint": "/status/sessions/terminate?sessionId={id}&reason=kicked", "auth": "token"},
        "jellyfin": {"method": "POST", "endpoint": "/Sessions/{sessionId}/Message", "auth": "bearer"},
        "emby": {"method": "DELETE", "endpoint": "/Sessions/{sessionId}", "auth": "bearer"},
        "navidrome": {"method": "DELETE", "endpoint": "/api/player/{id}", "auth": "bearer"},
    },
    "media_metadata_refresh": {
        "plex": {"method": "PUT", "endpoint": "/library/metadata/{id}/refresh", "auth": "token"},
        "jellyfin": {"method": "POST", "endpoint": "/Items/{itemId}/Refresh", "auth": "bearer"},
        "emby": {"method": "POST", "endpoint": "/Items/{itemId}/Refresh", "auth": "bearer"},
        "navidrome": {"method": "exec", "command": "navidrome --rescan", "auth": "local"},
    },
})

_register_category("media_management", {
    "servarr_queue_clear": {
        "radarr": {"method": "DELETE", "endpoint": "/api/v3/queue/bulk", "auth": "bearer"},
        "sonarr": {"method": "DELETE", "endpoint": "/api/v3/queue/bulk", "auth": "bearer"},
        "lidarr": {"method": "DELETE", "endpoint": "/api/v1/queue/bulk", "auth": "bearer"},
        "prowlarr": {"method": "DELETE", "endpoint": "/api/v1/queue/bulk", "auth": "bearer"},
        "readarr": {"method": "DELETE", "endpoint": "/api/v1/queue/bulk", "auth": "bearer"},
    },
    "servarr_failed_retry": {
        "radarr": {"method": "POST", "endpoint": "/api/v3/queue/failed/{id}", "auth": "bearer"},
        "sonarr": {"method": "POST", "endpoint": "/api/v3/queue/failed/{id}", "auth": "bearer"},
        "lidarr": {"method": "POST", "endpoint": "/api/v1/queue/failed/{id}", "auth": "bearer"},
        "prowlarr": {"method": "POST", "endpoint": "/api/v1/queue/failed/{id}", "auth": "bearer"},
        "readarr": {"method": "POST", "endpoint": "/api/v1/queue/failed/{id}", "auth": "bearer"},
    },
    "servarr_indexer_reset": {
        "radarr": {"method": "POST", "endpoint": "/api/v3/indexer/testall", "auth": "bearer"},
        "sonarr": {"method": "POST", "endpoint": "/api/v3/indexer/testall", "auth": "bearer"},
        "lidarr": {"method": "POST", "endpoint": "/api/v1/indexer/testall", "auth": "bearer"},
        "prowlarr": {"method": "POST", "endpoint": "/api/v1/indexer/testall", "auth": "bearer"},
        "readarr": {"method": "POST", "endpoint": "/api/v1/indexer/testall", "auth": "bearer"},
    },
    "servarr_import_scan": {
        "radarr": {"method": "POST", "endpoint": "/api/v3/command", "auth": "bearer"},
        "sonarr": {"method": "POST", "endpoint": "/api/v3/command", "auth": "bearer"},
        "lidarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
        "prowlarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
        "readarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
    },
    "servarr_cache_clear": {
        "radarr": {"method": "POST", "endpoint": "/api/v3/command", "auth": "bearer"},
        "sonarr": {"method": "POST", "endpoint": "/api/v3/command", "auth": "bearer"},
        "lidarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
        "prowlarr": {"method": "DELETE", "endpoint": "/api/v1/cache", "auth": "bearer"},
        "readarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
    },
    "servarr_task_restart": {
        "radarr": {"method": "POST", "endpoint": "/api/v3/command", "auth": "bearer"},
        "sonarr": {"method": "POST", "endpoint": "/api/v3/command", "auth": "bearer"},
        "lidarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
        "prowlarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
        "readarr": {"method": "POST", "endpoint": "/api/v1/command", "auth": "bearer"},
    },
})

_register_category("download_client", {
    "download_resume_all": {
        "qbittorrent": {"method": "POST", "endpoint": "/api/v2/torrents/resume", "auth": "session"},
        "transmission": {"method": "POST", "endpoint": "/transmission/rpc", "auth": "session"},
        "deluge": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "sabnzbd": {"method": "GET", "endpoint": "/sabnzbd/api?mode=resume", "auth": "apikey"},
    },
    "download_clear_stuck": {
        "qbittorrent": {"method": "POST", "endpoint": "/api/v2/torrents/delete", "auth": "session"},
        "transmission": {"method": "POST", "endpoint": "/transmission/rpc", "auth": "session"},
        "deluge": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "sabnzbd": {"method": "GET", "endpoint": "/sabnzbd/api?mode=purge_history", "auth": "apikey"},
    },
    "download_recheck_torrents": {
        "qbittorrent": {"method": "POST", "endpoint": "/api/v2/torrents/recheck", "auth": "session"},
        "transmission": {"method": "POST", "endpoint": "/transmission/rpc", "auth": "session"},
        "deluge": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "sabnzbd": {"method": "GET", "endpoint": "/sabnzbd/api?mode=check_quota", "auth": "apikey"},
    },
    "download_force_reannounce": {
        "qbittorrent": {"method": "POST", "endpoint": "/api/v2/torrents/reannounce", "auth": "session"},
        "transmission": {"method": "POST", "endpoint": "/transmission/rpc", "auth": "session"},
        "deluge": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "sabnzbd": {"method": "exec", "command": "sabcmd status", "auth": "local"},
    },
    "download_connection_reset": {
        "qbittorrent": {"method": "POST", "endpoint": "/api/v2/app/setPreferences", "auth": "session"},
        "transmission": {"method": "POST", "endpoint": "/transmission/rpc", "auth": "session"},
        "deluge": {"method": "exec", "command": "systemctl restart deluged", "auth": "local"},
        "sabnzbd": {"method": "exec", "command": "systemctl restart sabnzbd", "auth": "local"},
    },
})

_register_category("vpn", {
    "vpn_reconnect": {
        "tailscale": {"method": "exec", "command": "tailscale up --reset", "auth": "local"},
        "wireguard": {"method": "exec", "command": "wg-quick down {iface} && wg-quick up {iface}", "auth": "local"},
        "openvpn": {"method": "exec", "command": "systemctl restart openvpn@{config}", "auth": "local"},
        "zerotier": {"method": "POST", "endpoint": "/network/{networkId}/member/{nodeId}", "auth": "bearer"},
        "cloudflared": {"method": "exec", "command": "systemctl restart cloudflared", "auth": "local"},
    },
    "vpn_key_rotate": {
        "tailscale": {"method": "exec", "command": "tailscale logout && tailscale up --authkey={key}", "auth": "local"},
        "wireguard": {"method": "exec", "command": "wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key", "auth": "local"},
        "openvpn": {"method": "exec", "command": "easyrsa renew {client}", "auth": "local"},
        "zerotier": {"method": "POST", "endpoint": "/network/{networkId}/member/{nodeId}/regenerate", "auth": "bearer"},
        "cloudflared": {"method": "exec", "command": "cloudflared tunnel token --cred-file /etc/cloudflared/creds.json {tunnel}", "auth": "local"},
    },
    "vpn_route_refresh": {
        "tailscale": {"method": "exec", "command": "tailscale set --advertise-routes={routes}", "auth": "local"},
        "wireguard": {"method": "exec", "command": "ip route flush table main && wg-quick up {iface}", "auth": "local"},
        "openvpn": {"method": "exec", "command": "kill -HUP $(pidof openvpn)", "auth": "local"},
        "zerotier": {"method": "PUT", "endpoint": "/network/{networkId}/member/{nodeId}", "auth": "bearer"},
        "cloudflared": {"method": "exec", "command": "cloudflared tunnel route ip {cidr} {tunnel}", "auth": "local"},
    },
    "vpn_peer_reset": {
        "tailscale": {"method": "exec", "command": "tailscale ping --until-direct {peer}", "auth": "local"},
        "wireguard": {"method": "exec", "command": "wg set {iface} peer {pubkey} endpoint {endpoint}", "auth": "local"},
        "openvpn": {"method": "exec", "command": "echo 'client-kill {id}' | nc -q1 127.0.0.1 7505", "auth": "local"},
        "zerotier": {"method": "DELETE", "endpoint": "/network/{networkId}/member/{nodeId}", "auth": "bearer"},
        "cloudflared": {"method": "exec", "command": "cloudflared tunnel info {tunnel}", "auth": "local"},
    },
    "vpn_tunnel_restart": {
        "tailscale": {"method": "exec", "command": "systemctl restart tailscaled", "auth": "local"},
        "wireguard": {"method": "exec", "command": "systemctl restart wg-quick@{iface}", "auth": "local"},
        "openvpn": {"method": "exec", "command": "systemctl restart openvpn@{config}", "auth": "local"},
        "zerotier": {"method": "exec", "command": "systemctl restart zerotier-one", "auth": "local"},
        "cloudflared": {"method": "exec", "command": "cloudflared tunnel run {tunnel}", "auth": "local"},
    },
})

_register_category("monitoring", {
    "monitor_force_check": {
        "kuma": {"method": "POST", "endpoint": "/api/monitor/{id}/force-check", "auth": "bearer"},
        "grafana": {"method": "POST", "endpoint": "/api/alerting/rules/{uid}/force-check", "auth": "bearer"},
        "zabbix": {"method": "POST", "endpoint": "/api_jsonrpc.php", "auth": "session"},
        "prometheus": {"method": "exec", "command": "curl -X POST http://localhost:9090/-/reload", "auth": "local"},
    },
    "monitor_clear_downtime": {
        "kuma": {"method": "DELETE", "endpoint": "/api/monitor/{id}/downtime", "auth": "bearer"},
        "grafana": {"method": "DELETE", "endpoint": "/api/alerting/silence/{id}", "auth": "bearer"},
        "zabbix": {"method": "POST", "endpoint": "/api_jsonrpc.php", "auth": "session"},
        "prometheus": {"method": "DELETE", "endpoint": "/api/v1/silences/{id}", "auth": "local"},
    },
    "monitor_restart_agent": {
        "kuma": {"method": "exec", "command": "systemctl restart uptime-kuma", "auth": "local"},
        "grafana": {"method": "exec", "command": "systemctl restart grafana-agent", "auth": "local"},
        "zabbix": {"method": "exec", "command": "systemctl restart zabbix-agent2", "auth": "local"},
        "prometheus": {"method": "exec", "command": "systemctl restart prometheus", "auth": "local"},
    },
    "monitor_acknowledge_alert": {
        "kuma": {"method": "POST", "endpoint": "/api/monitor/{id}/ack", "auth": "bearer"},
        "grafana": {"method": "PATCH", "endpoint": "/api/alerting/alerts/{id}", "auth": "bearer"},
        "zabbix": {"method": "POST", "endpoint": "/api_jsonrpc.php", "auth": "session"},
        "prometheus": {"method": "POST", "endpoint": "/api/v1/alerts/{id}/ack", "auth": "local"},
    },
    "monitor_silence_rule": {
        "kuma": {"method": "POST", "endpoint": "/api/monitor/{id}/pause", "auth": "bearer"},
        "grafana": {"method": "POST", "endpoint": "/api/alerting/silence", "auth": "bearer"},
        "zabbix": {"method": "POST", "endpoint": "/api_jsonrpc.php", "auth": "session"},
        "prometheus": {"method": "POST", "endpoint": "/api/v1/silences", "auth": "local"},
    },
})

_register_category("smart_home", {
    "home_reload_config": {
        "homeassistant": {"method": "POST", "endpoint": "/api/config/core/reload", "auth": "bearer"},
        "openhab": {"method": "POST", "endpoint": "/rest/config/reload", "auth": "bearer"},
        "hubitat": {"method": "POST", "endpoint": "/hub/reload", "auth": "session"},
    },
    "home_restart_integration": {
        "homeassistant": {"method": "POST", "endpoint": "/api/config/config_entries/entry/{entry_id}/reload", "auth": "bearer"},
        "openhab": {"method": "POST", "endpoint": "/rest/things/{thingUID}/enable", "auth": "bearer"},
        "hubitat": {"method": "POST", "endpoint": "/hub/app/{id}/restart", "auth": "session"},
    },
    "home_automation_toggle": {
        "homeassistant": {"method": "POST", "endpoint": "/api/services/automation/toggle", "auth": "bearer"},
        "openhab": {"method": "POST", "endpoint": "/rest/rules/{ruleUID}/enable", "auth": "bearer"},
        "hubitat": {"method": "POST", "endpoint": "/hub/app/{id}/pause", "auth": "session"},
    },
    "home_device_rediscover": {
        "homeassistant": {"method": "POST", "endpoint": "/api/services/zeroconf/discover", "auth": "bearer"},
        "openhab": {"method": "GET", "endpoint": "/rest/discovery/bindings/{bindingId}/scan", "auth": "bearer"},
        "hubitat": {"method": "POST", "endpoint": "/hub/discover", "auth": "session"},
    },
    "home_zigbee_rejoin": {
        "homeassistant": {"method": "POST", "endpoint": "/api/services/zha/permit", "auth": "bearer"},
        "openhab": {"method": "POST", "endpoint": "/rest/things/{thingUID}/config", "auth": "bearer"},
        "hubitat": {"method": "POST", "endpoint": "/hub/zigbee/rejoin", "auth": "session"},
    },
})

_register_category("identity_auth", {
    "auth_session_flush": {
        "authentik": {"method": "POST", "endpoint": "/api/v3/core/tokens/expire_tokens/", "auth": "bearer"},
        "authelia": {"method": "POST", "endpoint": "/api/admin/sessions/revoke", "auth": "bearer"},
        "keycloak": {"method": "DELETE", "endpoint": "/admin/realms/{realm}/sessions/{id}", "auth": "bearer"},
    },
    "auth_cache_clear": {
        "authentik": {"method": "POST", "endpoint": "/api/v3/admin/system/", "auth": "bearer"},
        "authelia": {"method": "POST", "endpoint": "/api/admin/cache/flush", "auth": "bearer"},
        "keycloak": {"method": "POST", "endpoint": "/admin/realms/{realm}/clear-user-cache", "auth": "bearer"},
    },
    "auth_provider_reconnect": {
        "authentik": {"method": "POST", "endpoint": "/api/v3/sources/{slug}/refresh/", "auth": "bearer"},
        "authelia": {"method": "POST", "endpoint": "/api/admin/ldap/reconnect", "auth": "bearer"},
        "keycloak": {"method": "POST", "endpoint": "/admin/realms/{realm}/ldap-server-capabilities", "auth": "bearer"},
    },
    "auth_ldap_sync": {
        "authentik": {"method": "POST", "endpoint": "/api/v3/sources/ldap/{slug}/sync/", "auth": "bearer"},
        "authelia": {"method": "POST", "endpoint": "/api/admin/ldap/sync", "auth": "bearer"},
        "keycloak": {"method": "POST", "endpoint": "/admin/realms/{realm}/user-storage/{id}/sync", "auth": "bearer"},
    },
    "auth_token_revoke_expired": {
        "authentik": {"method": "POST", "endpoint": "/api/v3/core/tokens/expire_tokens/", "auth": "bearer"},
        "authelia": {"method": "DELETE", "endpoint": "/api/admin/tokens/expired", "auth": "bearer"},
        "keycloak": {"method": "POST", "endpoint": "/admin/realms/{realm}/revoke-refresh-token", "auth": "bearer"},
    },
})

_register_category("backup", {
    "backup_trigger": {
        "borg": {"method": "exec", "command": "borg create {repo}::{archive_name} {paths}", "auth": "local"},
        "restic": {"method": "exec", "command": "restic -r {repo} backup {paths}", "auth": "local"},
        "duplicati": {"method": "POST", "endpoint": "/api/v1/backup/{id}/run", "auth": "session"},
        "kopia": {"method": "exec", "command": "kopia snapshot create {path}", "auth": "local"},
        "pbs": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/backup", "auth": "bearer"},
    },
    "backup_verify": {
        "borg": {"method": "exec", "command": "borg check {repo}", "auth": "local"},
        "restic": {"method": "exec", "command": "restic -r {repo} check", "auth": "local"},
        "duplicati": {"method": "POST", "endpoint": "/api/v1/backup/{id}/verify", "auth": "session"},
        "kopia": {"method": "exec", "command": "kopia snapshot verify", "auth": "local"},
        "pbs": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/backup/verify", "auth": "bearer"},
    },
    "backup_prune_old": {
        "borg": {"method": "exec", "command": "borg prune {repo} --keep-daily={days}", "auth": "local"},
        "restic": {"method": "exec", "command": "restic -r {repo} forget --prune --keep-daily={days}", "auth": "local"},
        "duplicati": {"method": "POST", "endpoint": "/api/v1/backup/{id}/delete", "auth": "session"},
        "kopia": {"method": "exec", "command": "kopia snapshot expire --all", "auth": "local"},
        "pbs": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/gc", "auth": "bearer"},
    },
    "backup_retry_failed": {
        "borg": {"method": "exec", "command": "borg create --stats --retry=3 {repo}::{archive} {paths}", "auth": "local"},
        "restic": {"method": "exec", "command": "restic -r {repo} backup --retry-lock 5m {paths}", "auth": "local"},
        "duplicati": {"method": "POST", "endpoint": "/api/v1/backup/{id}/run", "auth": "session"},
        "kopia": {"method": "exec", "command": "kopia snapshot create --retry {path}", "auth": "local"},
        "pbs": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/backup", "auth": "bearer"},
    },
    "backup_integrity_check": {
        "borg": {"method": "exec", "command": "borg check --verify-data {repo}", "auth": "local"},
        "restic": {"method": "exec", "command": "restic -r {repo} check --read-data", "auth": "local"},
        "duplicati": {"method": "POST", "endpoint": "/api/v1/backup/{id}/verify", "auth": "session"},
        "kopia": {"method": "exec", "command": "kopia blob verify", "auth": "local"},
        "pbs": {"method": "POST", "endpoint": "/api2/json/nodes/{node}/backup/verify_data", "auth": "bearer"},
    },
    "backup_mount_check": {
        "borg": {"method": "exec", "command": "borg mount {repo} /mnt/borg-check && ls /mnt/borg-check && borg umount /mnt/borg-check", "auth": "local"},
        "restic": {"method": "exec", "command": "restic -r {repo} mount /mnt/restic-check", "auth": "local"},
        "duplicati": {"method": "GET", "endpoint": "/api/v1/backup/{id}/files", "auth": "session"},
        "kopia": {"method": "exec", "command": "kopia mount all /mnt/kopia-check", "auth": "local"},
        "pbs": {"method": "GET", "endpoint": "/api2/json/nodes/{node}/storage/{storage}/content", "auth": "bearer"},
    },
})

_register_category("certificate", {
    "cert_renew": {
        "certbot": {"method": "exec", "command": "certbot renew --cert-name {domain}", "auth": "local"},
        "acmesh": {"method": "exec", "command": "acme.sh --renew -d {domain}", "auth": "local"},
        "caddy": {"method": "POST", "endpoint": "/certificates/renew/{id}", "auth": "bearer"},
        "vault_pki": {"method": "POST", "endpoint": "/v1/{mount}/issue/{role}", "auth": "bearer"},
    },
    "cert_chain_fix": {
        "certbot": {"method": "exec", "command": "certbot certificates && certbot renew --force-renewal --cert-name {domain}", "auth": "local"},
        "acmesh": {"method": "exec", "command": "acme.sh --renew -d {domain} --force", "auth": "local"},
        "caddy": {"method": "POST", "endpoint": "/certificates/{id}/reload", "auth": "bearer"},
        "vault_pki": {"method": "POST", "endpoint": "/v1/{mount}/intermediate/set-signed", "auth": "bearer"},
    },
    "cert_deploy_reload": {
        "certbot": {"method": "exec", "command": "certbot renew --deploy-hook 'systemctl reload nginx'", "auth": "local"},
        "acmesh": {"method": "exec", "command": "acme.sh --deploy -d {domain} --deploy-hook {hook}", "auth": "local"},
        "caddy": {"method": "exec", "command": "caddy reload --config /etc/caddy/Caddyfile", "auth": "local"},
        "vault_pki": {"method": "PUT", "endpoint": "/v1/{mount}/config/urls", "auth": "bearer"},
    },
    "cert_ocsp_refresh": {
        "certbot": {"method": "exec", "command": "openssl ocsp -issuer {ca_cert} -cert {cert} -url {ocsp_url}", "auth": "local"},
        "acmesh": {"method": "exec", "command": "acme.sh --revoke -d {domain}", "auth": "local"},
        "caddy": {"method": "POST", "endpoint": "/certificates/{id}/ocsp", "auth": "bearer"},
        "vault_pki": {"method": "GET", "endpoint": "/v1/{mount}/ocsp", "auth": "bearer"},
    },
    "cert_revoke_replace": {
        "certbot": {"method": "exec", "command": "certbot revoke --cert-path {cert_path} && certbot certonly -d {domain}", "auth": "local"},
        "acmesh": {"method": "exec", "command": "acme.sh --revoke -d {domain} && acme.sh --issue -d {domain}", "auth": "local"},
        "caddy": {"method": "DELETE", "endpoint": "/certificates/{id}", "auth": "bearer"},
        "vault_pki": {"method": "POST", "endpoint": "/v1/{mount}/revoke", "auth": "bearer"},
    },
})

_register_category("database", {
    "db_connection_pool_reset": {
        "postgresql": {"method": "exec", "command": "psql -c 'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = $1' 'idle'", "auth": "local"},
        "mysql": {"method": "exec", "command": "mysql -e 'FLUSH HOSTS; KILL CONNECTION {id};'", "auth": "local"},
        "redis": {"method": "exec", "command": "redis-cli CLIENT KILL TYPE normal", "auth": "local"},
        "mongodb": {"method": "exec", "command": "mongo admin --eval 'db.currentOp().inprog.forEach(function(op){if(op.secs_running>300)db.killOp(op.opid)})'", "auth": "local"},
        "influxdb": {"method": "exec", "command": "systemctl restart influxdb", "auth": "local"},
    },
    "db_cache_flush": {
        "postgresql": {"method": "exec", "command": "psql -c 'DISCARD ALL;'", "auth": "local"},
        "mysql": {"method": "exec", "command": "mysql -e 'FLUSH TABLES; RESET QUERY CACHE;'", "auth": "local"},
        "redis": {"method": "exec", "command": "redis-cli FLUSHDB ASYNC", "auth": "local"},
        "mongodb": {"method": "exec", "command": "mongo admin --eval 'db.runCommand({planCacheClear: 1})'", "auth": "local"},
        "influxdb": {"method": "exec", "command": "influx query 'DROP MEASUREMENT cache'", "auth": "local"},
    },
    "db_replication_sync": {
        "postgresql": {"method": "exec", "command": "psql -c 'SELECT pg_wal_replay_resume();'", "auth": "local"},
        "mysql": {"method": "exec", "command": "mysql -e 'START REPLICA;'", "auth": "local"},
        "redis": {"method": "exec", "command": "redis-cli SLAVEOF {master} {port}", "auth": "local"},
        "mongodb": {"method": "exec", "command": "mongo admin --eval 'rs.syncFrom(\"{source}\")'", "auth": "local"},
        "influxdb": {"method": "POST", "endpoint": "/api/v2/replication/{id}/validate", "auth": "bearer"},
    },
    "db_vacuum_analyze": {
        "postgresql": {"method": "exec", "command": "psql -c 'VACUUM ANALYZE;'", "auth": "local"},
        "mysql": {"method": "exec", "command": "mysqlcheck --all-databases --optimize", "auth": "local"},
        "redis": {"method": "exec", "command": "redis-cli OBJECT HELP", "auth": "local"},
        "mongodb": {"method": "exec", "command": "mongo admin --eval 'db.runCommand({compact: \"{collection}\"})'", "auth": "local"},
        "influxdb": {"method": "exec", "command": "influx admin compact", "auth": "local"},
    },
    "db_slow_query_kill": {
        "postgresql": {"method": "exec", "command": "psql -c 'SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE query_start < now() - interval $1' '5 minutes'", "auth": "local"},
        "mysql": {"method": "exec", "command": "mysql -e 'KILL QUERY {id};'", "auth": "local"},
        "redis": {"method": "exec", "command": "redis-cli CLIENT KILL ID {id}", "auth": "local"},
        "mongodb": {"method": "exec", "command": "mongo admin --eval 'db.killOp({opid})'", "auth": "local"},
        "influxdb": {"method": "exec", "command": "influx query kill {id}", "auth": "local"},
    },
    "db_index_rebuild": {
        "postgresql": {"method": "exec", "command": "psql -c 'REINDEX DATABASE {db};'", "auth": "local"},
        "mysql": {"method": "exec", "command": "mysqlcheck --all-databases --repair", "auth": "local"},
        "redis": {"method": "exec", "command": "redis-cli DEBUG RELOAD", "auth": "local"},
        "mongodb": {"method": "exec", "command": "mongo {db} --eval 'db.getCollectionNames().forEach(function(c){db[c].reIndex()})'", "auth": "local"},
        "influxdb": {"method": "exec", "command": "influx admin rebuild-index", "auth": "local"},
    },
})

_register_category("git_devops", {
    "git_gc_prune": {
        "gitea": {"method": "POST", "endpoint": "/api/v1/repos/{owner}/{repo}/git/gc", "auth": "bearer"},
        "gitlab": {"method": "POST", "endpoint": "/api/v4/projects/{id}/housekeeping", "auth": "bearer"},
        "forgejo": {"method": "POST", "endpoint": "/api/v1/repos/{owner}/{repo}/git/gc", "auth": "bearer"},
        "jenkins": {"method": "exec", "command": "git -C {workspace} gc --prune=now", "auth": "local"},
    },
    "git_runner_restart": {
        "gitea": {"method": "exec", "command": "systemctl restart gitea-runner", "auth": "local"},
        "gitlab": {"method": "exec", "command": "systemctl restart gitlab-runner", "auth": "local"},
        "forgejo": {"method": "exec", "command": "systemctl restart forgejo-runner", "auth": "local"},
        "jenkins": {"method": "POST", "endpoint": "/node/{name}/toggleOffline", "auth": "bearer"},
    },
    "ci_queue_clear": {
        "gitea": {"method": "DELETE", "endpoint": "/api/v1/repos/{owner}/{repo}/actions/queue", "auth": "bearer"},
        "gitlab": {"method": "DELETE", "endpoint": "/api/v4/projects/{id}/runners/queue", "auth": "bearer"},
        "forgejo": {"method": "DELETE", "endpoint": "/api/v1/repos/{owner}/{repo}/actions/queue", "auth": "bearer"},
        "jenkins": {"method": "POST", "endpoint": "/queue/cancelItem?id={id}", "auth": "bearer"},
    },
    "ci_stuck_job_kill": {
        "gitea": {"method": "DELETE", "endpoint": "/api/v1/repos/{owner}/{repo}/actions/runs/{run_id}", "auth": "bearer"},
        "gitlab": {"method": "POST", "endpoint": "/api/v4/projects/{id}/jobs/{job_id}/cancel", "auth": "bearer"},
        "forgejo": {"method": "DELETE", "endpoint": "/api/v1/repos/{owner}/{repo}/actions/runs/{run_id}", "auth": "bearer"},
        "jenkins": {"method": "POST", "endpoint": "/job/{job}/{build}/stop", "auth": "bearer"},
    },
    "ci_cache_purge": {
        "gitea": {"method": "DELETE", "endpoint": "/api/v1/repos/{owner}/{repo}/actions/caches", "auth": "bearer"},
        "gitlab": {"method": "DELETE", "endpoint": "/api/v4/projects/{id}/runners/cache", "auth": "bearer"},
        "forgejo": {"method": "DELETE", "endpoint": "/api/v1/repos/{owner}/{repo}/actions/caches", "auth": "bearer"},
        "jenkins": {"method": "exec", "command": "rm -rf {workspace}/.cache", "auth": "local"},
    },
})

_register_category("mail", {
    "mail_queue_flush": {
        "mailcow": {"method": "POST", "endpoint": "/api/v1/edit/mailq", "auth": "bearer"},
        "postfix": {"method": "exec", "command": "postqueue -f", "auth": "local"},
        "mailu": {"method": "POST", "endpoint": "/api/v1/mailq/flush", "auth": "bearer"},
    },
    "mail_queue_clear_stuck": {
        "mailcow": {"method": "DELETE", "endpoint": "/api/v1/delete/mailq", "auth": "bearer"},
        "postfix": {"method": "exec", "command": "postsuper -d ALL deferred", "auth": "local"},
        "mailu": {"method": "DELETE", "endpoint": "/api/v1/mailq/stuck", "auth": "bearer"},
    },
    "mail_service_restart": {
        "mailcow": {"method": "exec", "command": "docker restart mailcowdockerized-postfix-mailcow-1", "auth": "local"},
        "postfix": {"method": "exec", "command": "systemctl restart postfix", "auth": "local"},
        "mailu": {"method": "exec", "command": "docker restart mailu-smtp-1", "auth": "local"},
    },
    "mail_index_rebuild": {
        "mailcow": {"method": "POST", "endpoint": "/api/v1/edit/doveadm/reindex", "auth": "bearer"},
        "postfix": {"method": "exec", "command": "postmap /etc/postfix/virtual", "auth": "local"},
        "mailu": {"method": "exec", "command": "docker exec mailu-imap-1 doveadm index -u {user} INBOX", "auth": "local"},
    },
    "mail_spam_filter_update": {
        "mailcow": {"method": "POST", "endpoint": "/api/v1/edit/rspamd/flush_storage", "auth": "bearer"},
        "postfix": {"method": "exec", "command": "sa-update && systemctl reload spamassassin", "auth": "local"},
        "mailu": {"method": "exec", "command": "docker exec mailu-rspamd-1 rspamadm configtest", "auth": "local"},
    },
})

_register_category("document_wiki", {
    "doc_reindex": {
        "paperless": {"method": "POST", "endpoint": "/api/documents/bulk_edit/", "auth": "bearer"},
        "nextcloud": {"method": "exec", "command": "php /var/www/nextcloud/occ files:scan --all", "auth": "local"},
        "bookstack": {"method": "POST", "endpoint": "/api/search/index", "auth": "bearer"},
        "wikijs": {"method": "POST", "endpoint": "/graphql", "auth": "bearer"},
    },
    "doc_cache_clear": {
        "paperless": {"method": "exec", "command": "python manage.py clearcache", "auth": "local"},
        "nextcloud": {"method": "exec", "command": "php /var/www/nextcloud/occ maintenance:repair", "auth": "local"},
        "bookstack": {"method": "exec", "command": "php artisan cache:clear", "auth": "local"},
        "wikijs": {"method": "exec", "command": "node wiki --clear-cache", "auth": "local"},
    },
    "doc_thumbnail_regen": {
        "paperless": {"method": "exec", "command": "python manage.py document_thumbnails", "auth": "local"},
        "nextcloud": {"method": "exec", "command": "php /var/www/nextcloud/occ preview:generate-all", "auth": "local"},
        "bookstack": {"method": "exec", "command": "php artisan bookstack:regenerate-thumbnails", "auth": "local"},
        "wikijs": {"method": "exec", "command": "node wiki --regen-thumbnails", "auth": "local"},
    },
    "doc_storage_optimize": {
        "paperless": {"method": "exec", "command": "python manage.py document_sanity_checker", "auth": "local"},
        "nextcloud": {"method": "exec", "command": "php /var/www/nextcloud/occ db:optimize", "auth": "local"},
        "bookstack": {"method": "exec", "command": "php artisan bookstack:clean-images", "auth": "local"},
        "wikijs": {"method": "exec", "command": "node wiki --optimize-storage", "auth": "local"},
    },
})

_register_category("security", {
    "security_unban_ip": {
        "crowdsec": {"method": "DELETE", "endpoint": "/v1/decisions?ip={ip}", "auth": "bearer"},
        "fail2ban": {"method": "exec", "command": "fail2ban-client set {jail} unbanip {ip}", "auth": "local"},
        "wazuh": {"method": "DELETE", "endpoint": "/security/rules/{id}", "auth": "bearer"},
        "vaultwarden": {"method": "exec", "command": "vaultwarden --unban {ip}", "auth": "local"},
    },
    "security_rule_reload": {
        "crowdsec": {"method": "POST", "endpoint": "/v1/decisions/reload", "auth": "bearer"},
        "fail2ban": {"method": "exec", "command": "fail2ban-client reload", "auth": "local"},
        "wazuh": {"method": "PUT", "endpoint": "/manager/configuration/reload", "auth": "bearer"},
        "vaultwarden": {"method": "exec", "command": "systemctl reload vaultwarden", "auth": "local"},
    },
    "security_signature_update": {
        "crowdsec": {"method": "POST", "endpoint": "/v1/collections/refresh", "auth": "bearer"},
        "fail2ban": {"method": "exec", "command": "fail2ban-client status", "auth": "local"},
        "wazuh": {"method": "PUT", "endpoint": "/manager/update/ruleset", "auth": "bearer"},
        "vaultwarden": {"method": "exec", "command": "systemctl restart vaultwarden", "auth": "local"},
    },
    "security_quarantine_release": {
        "crowdsec": {"method": "DELETE", "endpoint": "/v1/decisions?scope=ip&value={ip}", "auth": "bearer"},
        "fail2ban": {"method": "exec", "command": "fail2ban-client set {jail} unbanip {ip}", "auth": "local"},
        "wazuh": {"method": "DELETE", "endpoint": "/security/groups/{id}/agents/{agent_id}", "auth": "bearer"},
        "vaultwarden": {"method": "exec", "command": "vaultwarden --release-quarantine {item}", "auth": "local"},
    },
    "security_scan_trigger": {
        "crowdsec": {"method": "POST", "endpoint": "/v1/alerts", "auth": "bearer"},
        "fail2ban": {"method": "exec", "command": "fail2ban-client status {jail}", "auth": "local"},
        "wazuh": {"method": "PUT", "endpoint": "/manager/files?path=etc/ossec.conf", "auth": "bearer"},
        "vaultwarden": {"method": "exec", "command": "vaultwarden --scan", "auth": "local"},
    },
})

_register_category("cloud_cdn", {
    "cdn_cache_purge": {
        "cloudflare": {"method": "POST", "endpoint": "/client/v4/zones/{zone_id}/purge_cache", "auth": "bearer"},
        "aws": {"method": "exec", "command": "aws cloudfront create-invalidation --distribution-id {id} --paths '/*'", "auth": "local"},
        "hetzner": {"method": "exec", "command": "hcloud server rebuild {server} --image {image}", "auth": "local"},
    },
    "cloud_instance_restart": {
        "cloudflare": {"method": "exec", "command": "wrangler deployment create --env {env}", "auth": "local"},
        "aws": {"method": "exec", "command": "aws ec2 reboot-instances --instance-ids {id}", "auth": "local"},
        "hetzner": {"method": "POST", "endpoint": "/v1/servers/{id}/actions/reboot", "auth": "bearer"},
    },
    "cloud_dns_failover": {
        "cloudflare": {"method": "PATCH", "endpoint": "/client/v4/zones/{zone_id}/dns_records/{id}", "auth": "bearer"},
        "aws": {"method": "exec", "command": "aws route53 change-resource-record-sets --hosted-zone-id {id} --change-batch file://failover.json", "auth": "local"},
        "hetzner": {"method": "PUT", "endpoint": "/v1/dns/zones/{zone_id}/records/{id}", "auth": "bearer"},
    },
    "cloud_ssl_redeploy": {
        "cloudflare": {"method": "PATCH", "endpoint": "/client/v4/zones/{zone_id}/settings/ssl", "auth": "bearer"},
        "aws": {"method": "exec", "command": "aws acm request-certificate --domain-name {domain}", "auth": "local"},
        "hetzner": {"method": "exec", "command": "hcloud load-balancer add-service --protocol https --https-certificates {cert_id}", "auth": "local"},
    },
    "cloud_firewall_rule": {
        "cloudflare": {"method": "POST", "endpoint": "/client/v4/zones/{zone_id}/firewall/rules", "auth": "bearer"},
        "aws": {"method": "exec", "command": "aws ec2 authorize-security-group-ingress --group-id {sg_id} --protocol tcp --port {port} --cidr {cidr}", "auth": "local"},
        "hetzner": {"method": "PUT", "endpoint": "/v1/firewalls/{id}/actions/set_rules", "auth": "bearer"},
    },
})

_register_category("network_hardware", {
    "net_restart_ap": {
        "unifi": {"method": "POST", "endpoint": "/api/s/{site}/cmd/devmgr", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/interface wireless disable [find name={iface}]; /interface wireless enable [find name={iface}]", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/interfaces/wireless/restart", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "wifi down && wifi up", "auth": "local"},
    },
    "net_reconnect_client": {
        "unifi": {"method": "POST", "endpoint": "/api/s/{site}/cmd/stamgr", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/interface wireless disconnect [find mac-address={mac}]", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/dhcpv4/leases/del/{mac}", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "hostapd_cli deauthenticate {mac}", "auth": "local"},
    },
    "net_port_bounce": {
        "unifi": {"method": "POST", "endpoint": "/api/s/{site}/cmd/devmgr", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/interface ethernet disable [find name={port}]; /interface ethernet enable [find name={port}]", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/interfaces/{iface}/bounce", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "swconfig dev switch0 port {n} set disable 1 && swconfig dev switch0 port {n} set disable 0", "auth": "local"},
    },
    "net_dhcp_release_renew": {
        "unifi": {"method": "POST", "endpoint": "/api/s/{site}/cmd/stamgr", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/ip dhcp-client release [find interface={iface}]; /ip dhcp-client renew [find interface={iface}]", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/dhcpv4/service/restart", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "udhcpc -i {iface} -n -q", "auth": "local"},
    },
    "net_vlan_reassign": {
        "unifi": {"method": "PUT", "endpoint": "/api/s/{site}/rest/user/{mac}", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/interface vlan set [find name={vlan}] vlan-id={new_id}", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/interfaces/vlan/addItem", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "uci set network.{iface}.vid={new_id} && uci commit network && /etc/init.d/network reload", "auth": "local"},
    },
    "net_firmware_apply": {
        "unifi": {"method": "POST", "endpoint": "/api/s/{site}/cmd/devmgr", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/system package update install", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/core/firmware/upgrade", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "sysupgrade /tmp/firmware.bin", "auth": "local"},
    },
    "net_routing_flush": {
        "unifi": {"method": "POST", "endpoint": "/api/s/{site}/cmd/devmgr", "auth": "session"},
        "mikrotik": {"method": "exec", "command": "/ip route flush", "auth": "local"},
        "opnsense": {"method": "POST", "endpoint": "/api/routes/routes/flushall", "auth": "bearer"},
        "openwrt": {"method": "exec", "command": "ip route flush table main && /etc/init.d/network restart", "auth": "local"},
    },
})

_register_category("power_ups", {
    "power_outlet_cycle": {
        "nut": {"method": "exec", "command": "upsrw -s {var}={val} {ups}", "auth": "local"},
        "apc": {"method": "exec", "command": "apcaccess status && apcupsd --poweroff", "auth": "local"},
        "shelly": {"method": "POST", "endpoint": "/relay/{id}", "auth": "session"},
        "tasmota": {"method": "GET", "endpoint": "/cm?cmnd=Power{n}+OFF+Power{n}+ON", "auth": "session"},
    },
    "power_ups_test": {
        "nut": {"method": "exec", "command": "upscmd {ups} test.battery.start", "auth": "local"},
        "apc": {"method": "exec", "command": "apctest", "auth": "local"},
        "shelly": {"method": "GET", "endpoint": "/status", "auth": "session"},
        "tasmota": {"method": "GET", "endpoint": "/cm?cmnd=Sensor10+test", "auth": "session"},
    },
    "power_load_shed": {
        "nut": {"method": "exec", "command": "upscmd {ups} load.off", "auth": "local"},
        "apc": {"method": "exec", "command": "apcupsd --killpower", "auth": "local"},
        "shelly": {"method": "POST", "endpoint": "/relay/{id}", "auth": "session"},
        "tasmota": {"method": "GET", "endpoint": "/cm?cmnd=Power{n}+OFF", "auth": "session"},
    },
    "power_schedule_shutdown": {
        "nut": {"method": "exec", "command": "upssched-cmd {action}", "auth": "local"},
        "apc": {"method": "exec", "command": "shutdown -h +{mins}", "auth": "local"},
        "shelly": {"method": "POST", "endpoint": "/timer/{id}", "auth": "session"},
        "tasmota": {"method": "GET", "endpoint": "/cm?cmnd=Timer1+{schedule}", "auth": "session"},
    },
    "power_battery_calibrate": {
        "nut": {"method": "exec", "command": "upscmd {ups} calibrate.start", "auth": "local"},
        "apc": {"method": "exec", "command": "apctest battery", "auth": "local"},
        "shelly": {"method": "POST", "endpoint": "/emeter/{n}/calibrate", "auth": "session"},
        "tasmota": {"method": "GET", "endpoint": "/cm?cmnd=EnergyReset+all", "auth": "session"},
    },
})

_register_category("surveillance", {
    "cam_restart_detector": {
        "frigate": {"method": "POST", "endpoint": "/api/restart", "auth": "bearer"},
        "blueiris": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "shinobi": {"method": "POST", "endpoint": "/{api_key}/monitorCmd/{group}/{monitor_id}/restart", "auth": "bearer"},
        "zoneminder": {"method": "POST", "endpoint": "/zm/api/monitors/{id}.json", "auth": "session"},
    },
    "cam_storage_cleanup": {
        "frigate": {"method": "DELETE", "endpoint": "/api/recordings/delete", "auth": "bearer"},
        "blueiris": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "shinobi": {"method": "DELETE", "endpoint": "/{api_key}/videos/{group}/{monitor_id}", "auth": "bearer"},
        "zoneminder": {"method": "DELETE", "endpoint": "/zm/api/events/index/StartTime%20<:{cutoff}.json", "auth": "session"},
    },
    "cam_restream": {
        "frigate": {"method": "POST", "endpoint": "/api/{camera_name}/ptz", "auth": "bearer"},
        "blueiris": {"method": "exec", "command": "BlueIris.exe /restream:{camera}", "auth": "local"},
        "shinobi": {"method": "POST", "endpoint": "/{api_key}/monitorCmd/{group}/{id}/start", "auth": "bearer"},
        "zoneminder": {"method": "exec", "command": "zmdc.pl restart zmc -m {monitor_id}", "auth": "local"},
    },
    "cam_motion_recalibrate": {
        "frigate": {"method": "PUT", "endpoint": "/api/config/set", "auth": "bearer"},
        "blueiris": {"method": "POST", "endpoint": "/json", "auth": "session"},
        "shinobi": {"method": "PUT", "endpoint": "/{api_key}/configureMonitor/{group}/{id}", "auth": "bearer"},
        "zoneminder": {"method": "PUT", "endpoint": "/zm/api/monitors/{id}.json", "auth": "session"},
    },
    "cam_recording_repair": {
        "frigate": {"method": "POST", "endpoint": "/api/recordings/repair", "auth": "bearer"},
        "blueiris": {"method": "exec", "command": "BlueIris.exe /repair:{camera}", "auth": "local"},
        "shinobi": {"method": "POST", "endpoint": "/{api_key}/videos/{group}/{id}/repair", "auth": "bearer"},
        "zoneminder": {"method": "exec", "command": "zmfix.pl -m {monitor_id}", "auth": "local"},
    },
})

_register_category("logging", {
    "log_index_rotate": {
        "graylog": {"method": "POST", "endpoint": "/api/system/indexer/indices/multiple", "auth": "session"},
        "loki": {"method": "POST", "endpoint": "/flush", "auth": "bearer"},
        "elasticsearch": {"method": "POST", "endpoint": "/_ilm/policy/{policy}/_execute", "auth": "bearer"},
        "splunk": {"method": "POST", "endpoint": "/services/data/indexes/{index}/roll-hot-buckets", "auth": "bearer"},
    },
    "log_retention_enforce": {
        "graylog": {"method": "PUT", "endpoint": "/api/system/indices/index_sets/{id}", "auth": "session"},
        "loki": {"method": "exec", "command": "logcli labels --retention={days}d", "auth": "local"},
        "elasticsearch": {"method": "PUT", "endpoint": "/_ilm/policy/{policy}", "auth": "bearer"},
        "splunk": {"method": "POST", "endpoint": "/services/data/indexes/{index}", "auth": "bearer"},
    },
    "log_pipeline_restart": {
        "graylog": {"method": "POST", "endpoint": "/api/system/inputs/{id}/launch", "auth": "session"},
        "loki": {"method": "exec", "command": "systemctl restart loki", "auth": "local"},
        "elasticsearch": {"method": "exec", "command": "systemctl restart elasticsearch", "auth": "local"},
        "splunk": {"method": "POST", "endpoint": "/services/server/control/restart", "auth": "bearer"},
    },
    "log_forwarder_reconnect": {
        "graylog": {"method": "PUT", "endpoint": "/api/system/inputs/{id}", "auth": "session"},
        "loki": {"method": "exec", "command": "systemctl restart promtail", "auth": "local"},
        "elasticsearch": {"method": "exec", "command": "systemctl restart logstash", "auth": "local"},
        "splunk": {"method": "POST", "endpoint": "/services/data/inputs/tcp/raw/{port}", "auth": "bearer"},
    },
    "log_alert_silence": {
        "graylog": {"method": "PUT", "endpoint": "/api/events/definitions/{id}", "auth": "session"},
        "loki": {"method": "DELETE", "endpoint": "/ruler/api/v1/rules/{namespace}/{group}", "auth": "bearer"},
        "elasticsearch": {"method": "PUT", "endpoint": "/_watcher/watch/{watch_id}/_deactivate", "auth": "bearer"},
        "splunk": {"method": "POST", "endpoint": "/services/saved/searches/{name}/suppress", "auth": "bearer"},
    },
})

_register_category("metrics", {
    "metrics_compaction": {
        "prometheus": {"method": "exec", "command": "promtool tsdb create-blocks-from openmetrics {file}", "auth": "local"},
        "influxdb": {"method": "POST", "endpoint": "/api/v2/orgs/{org_id}/compact", "auth": "bearer"},
        "victoriametrics": {"method": "GET", "endpoint": "/api/v1/admin/tsdb/snapshot", "auth": "bearer"},
        "thanos": {"method": "exec", "command": "thanos compact --data-dir={dir}", "auth": "local"},
    },
    "metrics_retention_enforce": {
        "prometheus": {"method": "exec", "command": "promtool tsdb analyze {dir}", "auth": "local"},
        "influxdb": {"method": "POST", "endpoint": "/api/v2/buckets/{id}", "auth": "bearer"},
        "victoriametrics": {"method": "GET", "endpoint": "/api/v1/admin/tsdb/delete_series", "auth": "bearer"},
        "thanos": {"method": "exec", "command": "thanos compact --retention.resolution-raw={days}d --data-dir={dir}", "auth": "local"},
    },
    "metrics_scrape_restart": {
        "prometheus": {"method": "POST", "endpoint": "/-/reload", "auth": "local"},
        "influxdb": {"method": "exec", "command": "systemctl restart influxdb", "auth": "local"},
        "victoriametrics": {"method": "GET", "endpoint": "/-/reload", "auth": "bearer"},
        "thanos": {"method": "exec", "command": "systemctl restart thanos-sidecar", "auth": "local"},
    },
    "metrics_cardinality_prune": {
        "prometheus": {"method": "POST", "endpoint": "/api/v1/admin/tsdb/delete_series", "auth": "local"},
        "influxdb": {"method": "DELETE", "endpoint": "/api/v2/delete", "auth": "bearer"},
        "victoriametrics": {"method": "GET", "endpoint": "/api/v1/admin/tsdb/delete_series", "auth": "bearer"},
        "thanos": {"method": "exec", "command": "thanos tools bucket web --objstore.config-file={config}", "auth": "local"},
    },
    "metrics_cache_clear": {
        "prometheus": {"method": "exec", "command": "systemctl restart prometheus", "auth": "local"},
        "influxdb": {"method": "exec", "command": "systemctl restart influxdb", "auth": "local"},
        "victoriametrics": {"method": "GET", "endpoint": "/internal/resetRollupResultCache", "auth": "bearer"},
        "thanos": {"method": "exec", "command": "systemctl restart thanos-query", "auth": "local"},
    },
})

_register_category("message_queue", {
    "queue_purge_dead_letters": {
        "rabbitmq": {"method": "DELETE", "endpoint": "/api/queues/{vhost}/{queue}/contents", "auth": "bearer"},
        "kafka": {"method": "exec", "command": "kafka-topics.sh --bootstrap-server {broker} --delete --topic {dlq_topic}", "auth": "local"},
        "mosquitto": {"method": "exec", "command": "mosquitto_sub -t '{dlq}' -C 1 && mosquitto_pub -t '{dlq}' -n", "auth": "local"},
        "nats": {"method": "exec", "command": "nats consumer purge {stream} {consumer}", "auth": "local"},
    },
    "queue_consumer_restart": {
        "rabbitmq": {"method": "POST", "endpoint": "/api/consumers/{vhost}", "auth": "bearer"},
        "kafka": {"method": "exec", "command": "kafka-consumer-groups.sh --bootstrap-server {broker} --group {group} --reset-offsets --to-latest --all-topics --execute", "auth": "local"},
        "mosquitto": {"method": "exec", "command": "systemctl restart mosquitto", "auth": "local"},
        "nats": {"method": "exec", "command": "nats server reload", "auth": "local"},
    },
    "queue_rebalance_partitions": {
        "rabbitmq": {"method": "POST", "endpoint": "/api/queues/{vhost}/{queue}/actions", "auth": "bearer"},
        "kafka": {"method": "exec", "command": "kafka-reassign-partitions.sh --bootstrap-server {broker} --reassignment-json-file plan.json --execute", "auth": "local"},
        "mosquitto": {"method": "exec", "command": "mosquitto_pub -t '$SYS/broker/reload' -n", "auth": "local"},
        "nats": {"method": "exec", "command": "nats stream cluster step-down {stream}", "auth": "local"},
    },
    "queue_connection_reset": {
        "rabbitmq": {"method": "DELETE", "endpoint": "/api/connections/{name}", "auth": "bearer"},
        "kafka": {"method": "exec", "command": "kafka-broker-api-versions.sh --bootstrap-server {broker}", "auth": "local"},
        "mosquitto": {"method": "exec", "command": "mosquitto_ctrl dynsec getClient {client}", "auth": "local"},
        "nats": {"method": "exec", "command": "nats server kick {conn_id}", "auth": "local"},
    },
    "queue_dlq_replay": {
        "rabbitmq": {"method": "POST", "endpoint": "/api/exchanges/{vhost}/{exchange}/publish", "auth": "bearer"},
        "kafka": {"method": "exec", "command": "kafka-console-consumer.sh --bootstrap-server {broker} --topic {dlq} --from-beginning | kafka-console-producer.sh --bootstrap-server {broker} --topic {src}", "auth": "local"},
        "mosquitto": {"method": "exec", "command": "mosquitto_sub -t '{dlq}' | mosquitto_pub -t '{src}' -l", "auth": "local"},
        "nats": {"method": "exec", "command": "nats consumer create {stream} --deliver all --filter {dlq}", "auth": "local"},
    },
})

_register_category("photo_management", {
    "photo_reindex": {
        "immich": {"method": "POST", "endpoint": "/api/jobs", "auth": "bearer"},
        "photoprism": {"method": "POST", "endpoint": "/api/v1/index", "auth": "bearer"},
        "lychee": {"method": "exec", "command": "php artisan lychee:scan", "auth": "local"},
    },
    "photo_thumbnail_regen": {
        "immich": {"method": "POST", "endpoint": "/api/jobs", "auth": "bearer"},
        "photoprism": {"method": "POST", "endpoint": "/api/v1/thumbs", "auth": "bearer"},
        "lychee": {"method": "exec", "command": "php artisan lychee:generate_thumbs", "auth": "local"},
    },
    "photo_ml_reprocess": {
        "immich": {"method": "POST", "endpoint": "/api/jobs", "auth": "bearer"},
        "photoprism": {"method": "POST", "endpoint": "/api/v1/faces", "auth": "bearer"},
        "lychee": {"method": "exec", "command": "php artisan lychee:reprocess", "auth": "local"},
    },
    "photo_storage_optimize": {
        "immich": {"method": "exec", "command": "immich-server --optimize-storage", "auth": "local"},
        "photoprism": {"method": "exec", "command": "photoprism optimize", "auth": "local"},
        "lychee": {"method": "exec", "command": "php artisan lychee:optimize", "auth": "local"},
    },
    "photo_duplicate_scan": {
        "immich": {"method": "POST", "endpoint": "/api/jobs", "auth": "bearer"},
        "photoprism": {"method": "POST", "endpoint": "/api/v1/duplicates", "auth": "bearer"},
        "lychee": {"method": "exec", "command": "php artisan lychee:find-duplicates", "auth": "local"},
    },
})

_register_category("automation_workflow", {
    "workflow_restart_stuck": {
        "n8n": {"method": "POST", "endpoint": "/api/v1/workflows/{id}/activate", "auth": "bearer"},
        "nodered": {"method": "POST", "endpoint": "/flows", "auth": "bearer"},
        "huginn": {"method": "POST", "endpoint": "/api/v1/agents/{id}/run", "auth": "bearer"},
    },
    "workflow_clear_queue": {
        "n8n": {"method": "DELETE", "endpoint": "/api/v1/executions", "auth": "bearer"},
        "nodered": {"method": "exec", "command": "node-red-admin flush-queue", "auth": "local"},
        "huginn": {"method": "DELETE", "endpoint": "/api/v1/agents/{id}/events", "auth": "bearer"},
    },
    "workflow_credential_refresh": {
        "n8n": {"method": "PUT", "endpoint": "/api/v1/credentials/{id}", "auth": "bearer"},
        "nodered": {"method": "PUT", "endpoint": "/credentials", "auth": "bearer"},
        "huginn": {"method": "exec", "command": "systemctl restart huginn", "auth": "local"},
    },
    "workflow_execution_cleanup": {
        "n8n": {"method": "DELETE", "endpoint": "/api/v1/executions/prune", "auth": "bearer"},
        "nodered": {"method": "exec", "command": "node-red-admin clear-log", "auth": "local"},
        "huginn": {"method": "DELETE", "endpoint": "/api/v1/events/bulk_destroy", "auth": "bearer"},
    },
})

_register_category("file_sync", {
    "sync_force_rescan": {
        "syncthing": {"method": "POST", "endpoint": "/rest/db/scan", "auth": "apikey"},
        "resilio": {"method": "POST", "endpoint": "/api/v4/folders/{folder_id}/rescan", "auth": "bearer"},
        "seafile": {"method": "POST", "endpoint": "/api2/repos/{repo_id}/rescan/", "auth": "bearer"},
    },
    "sync_conflict_resolve": {
        "syncthing": {"method": "DELETE", "endpoint": "/rest/db/file?folder={folder}&file={file}", "auth": "apikey"},
        "resilio": {"method": "POST", "endpoint": "/api/v4/folders/{folder_id}/conflicts/resolve", "auth": "bearer"},
        "seafile": {"method": "exec", "command": "seafile-admin repair-repo --repo {repo_id}", "auth": "local"},
    },
    "sync_connection_reset": {
        "syncthing": {"method": "POST", "endpoint": "/rest/system/restart", "auth": "apikey"},
        "resilio": {"method": "exec", "command": "systemctl restart resilio-sync", "auth": "local"},
        "seafile": {"method": "exec", "command": "systemctl restart seafile seahub", "auth": "local"},
    },
    "sync_index_rebuild": {
        "syncthing": {"method": "POST", "endpoint": "/rest/db/scan?folder={folder}&sub=", "auth": "apikey"},
        "resilio": {"method": "POST", "endpoint": "/api/v4/folders/{folder_id}/reindex", "auth": "bearer"},
        "seafile": {"method": "exec", "command": "seafile-admin rebuild-index --repo {repo_id}", "auth": "local"},
    },
})
