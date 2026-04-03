# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – System metrics package. Re-exports all public symbols for backward compatibility."""
from __future__ import annotations

from .hardware import collect_hardware, collect_smart, get_ipmi_sensors
from .network import (
    check_cert_expiry,
    check_device_presence,
    check_domain_expiry,
    collect_network,
    collect_per_interface_net,
    get_net_io,
    get_network_connections,
    get_listening_ports,
    get_tailscale_status,
    get_vpn_status,
    human_bps,
    ping_host,
)
from .services import (
    bust_container_cache,
    check_docker_updates,
    get_containers,
    get_process_history,
    get_service_status,
    probe_game_server,
    query_source_server,
    send_wol,
    snapshot_top_processes,
)
from .storage import collect_disk_io, collect_storage, get_rclone_remotes
from .system import collect_system, get_cpu_governor, get_cpu_history, get_cpu_percent
from .util import (
    TTLCache,
    _cache,
    _fmt_bytes,
    _read_file,
    _run,
    strip_ansi,
    validate_ip,
    validate_service_name,
)

__all__ = [
    # util
    "strip_ansi",
    "_read_file",
    "TTLCache",
    "_cache",
    "_run",
    "validate_ip",
    "validate_service_name",
    "_fmt_bytes",
    # system
    "collect_system",
    "get_cpu_percent",
    "get_cpu_history",
    "get_cpu_governor",
    # hardware
    "collect_hardware",
    "collect_smart",
    "get_ipmi_sensors",
    # network
    "collect_network",
    "collect_per_interface_net",
    "get_net_io",
    "human_bps",
    "get_network_connections",
    "get_listening_ports",
    "ping_host",
    "check_device_presence",
    "check_cert_expiry",
    "check_domain_expiry",
    "get_vpn_status",
    "get_tailscale_status",
    # storage
    "collect_storage",
    "collect_disk_io",
    "get_rclone_remotes",
    # services
    "get_service_status",
    "get_containers",
    "bust_container_cache",
    "check_docker_updates",
    "send_wol",
    "snapshot_top_processes",
    "get_process_history",
    "probe_game_server",
    "query_source_server",
]
