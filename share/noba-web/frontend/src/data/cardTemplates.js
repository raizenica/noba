// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
/**
 * Card templates for integration instances.
 * Each template defines what metrics to display for a given platform.
 * IntegrationCard.vue uses these to render platform-appropriate metrics.
 */
export const CARD_TEMPLATES = {
  // NAS
  truenas: {
    icon: 'fas fa-database',
    metrics: [
      { key: 'pool_status',  label: 'Pool',    type: 'status' },
      { key: 'running_apps', label: 'Apps',    type: 'number' },
      { key: 'alert_count',  label: 'Alerts',  type: 'number' },
    ],
  },
  synology: {
    icon: 'fas fa-database',
    metrics: [
      { key: 'volume_status', label: 'Volume', type: 'status' },
      { key: 'volume_used_pct', label: 'Used', type: 'percent_bar' },
      { key: 'drive_health', label: 'Drives', type: 'status' },
    ],
  },
  qnap: {
    icon: 'fas fa-database',
    metrics: [
      { key: 'raid_status', label: 'RAID', type: 'status' },
      { key: 'volume_used_pct', label: 'Used', type: 'percent_bar' },
      { key: 'drive_temp_max', label: 'Drive Temp', type: 'temperature' },
    ],
  },

  // Hypervisors
  proxmox: {
    icon: 'fas fa-server',
    metrics: [
      { key: 'node_status', label: 'Node', type: 'status' },
      { key: 'cpu_percent', label: 'CPU',  type: 'percent_bar' },
      { key: 'mem_percent', label: 'RAM',  type: 'percent_bar' },
      { key: 'vm_count',    label: 'VMs',  type: 'number' },
    ],
  },
  vmware: {
    icon: 'fas fa-server',
    metrics: [
      { key: 'host_status', label: 'Host', type: 'status' },
      { key: 'cpu_percent', label: 'CPU', type: 'percent_bar' },
      { key: 'vm_count', label: 'VMs', type: 'number' },
    ],
  },
  hyperv: {
    icon: 'fas fa-server',
    metrics: [
      { key: 'host_status', label: 'Host', type: 'status' },
      { key: 'vm_count', label: 'VMs', type: 'number' },
      { key: 'running_vms', label: 'Running', type: 'number' },
    ],
  },

  // DNS
  pihole: {
    icon: 'fas fa-shield-alt',
    metrics: [
      { key: 'status', label: 'Status', type: 'status' },
      { key: 'queries_today', label: 'Queries', type: 'number' },
      { key: 'ads_blocked_today', label: 'Blocked', type: 'number' },
      { key: 'ads_percentage_today', label: 'Block %', type: 'percent_bar' },
    ],
  },
  adguard: {
    icon: 'fas fa-shield-alt',
    metrics: [
      { key: 'status', label: 'Status', type: 'status' },
      { key: 'num_dns_queries', label: 'Queries', type: 'number' },
      { key: 'num_blocked_filtering', label: 'Blocked', type: 'number' },
    ],
  },

  // Media
  plex: {
    icon: 'fas fa-film',
    metrics: [
      { key: 'status',      label: 'Status',  type: 'status' },
      { key: 'connections', label: 'Streams', type: 'number' },
      { key: 'activities',  label: 'Active',  type: 'number' },
    ],
  },
  jellyfin: {
    icon: 'fas fa-film',
    metrics: [
      { key: 'status',       label: 'Status', type: 'status' },
      { key: 'movie_count',  label: 'Movies', type: 'number' },
      { key: 'series_count', label: 'Series', type: 'number' },
    ],
  },

  // Monitoring
  kuma: {
    icon: 'fas fa-heartbeat',
    metrics: [
      { key: 'status', label: 'Status', type: 'status' },
      { key: 'monitors_up', label: 'Up', type: 'number' },
      { key: 'monitors_down', label: 'Down', type: 'number' },
    ],
  },

  // Network
  unifi: {
    icon: 'fas fa-wifi',
    metrics: [
      { key: 'status', label: 'Controller', type: 'status' },
      { key: 'num_ap', label: 'APs', type: 'number' },
      { key: 'num_clients', label: 'Clients', type: 'number' },
    ],
  },

  // Fallback for unknown platforms
  _default: {
    icon: 'fas fa-plug',
    metrics: [
      { key: 'status', label: 'Status', type: 'status' },
    ],
  },
}

export function getTemplate(platform) {
  return CARD_TEMPLATES[platform] || CARD_TEMPLATES._default
}
