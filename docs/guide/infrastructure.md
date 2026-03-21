# Infrastructure

The Infrastructure section provides visibility and control over services, Kubernetes clusters, Proxmox nodes, network topology, and configuration drift.

## Services

Navigate to **Infrastructure → Services** to see all systemd services monitored across the NOBA server and connected agents.

- **Start / Stop / Restart** — buttons appear for operator and admin roles.
- **Filter** — search by service name or status.
- **Auto-refresh** — service status refreshes every 10 seconds via SSE.

Configure which services are monitored in **Settings → Integrations → Monitored Services**.

## Kubernetes

Connect a Kubernetes cluster in **Settings → Integrations → Kubernetes**.

Supported views:

| View | Contents |
|------|---------|
| Nodes | Node status, CPU/memory requests and limits |
| Namespaces | Namespace list with resource counts |
| Pods | Pod status, restart count, age, container images |
| Deployments | Desired vs. ready replica counts |
| Services | ClusterIP, NodePort, LoadBalancer services |
| Events | Warning and normal events, filterable by namespace |

Connection methods:
- **Kubeconfig file** — upload your `~/.kube/config`.
- **In-cluster** — if NOBA itself runs inside Kubernetes, it uses the pod's service account automatically.

## Proxmox

Connect Proxmox VE in **Settings → Integrations → Proxmox**.

Supported views:

| View | Contents |
|------|---------|
| Nodes | Node status, CPU, memory, storage |
| VMs | VM status, VMID, CPU/memory config |
| LXC | Container status and config |
| Storage | Pool usage across all storage backends |
| Cluster | HA status, quorum, corosync health |

VM and LXC actions (start, stop, reboot, shutdown) are available for operator and admin roles.

## Network Map

Navigate to **Infrastructure → Network** to see a live topology diagram of all monitored hosts:

- Nodes represent NOBA agents, Proxmox VMs, and Radar ping targets.
- Edges represent reachability (derived from ping/TCP monitor results).
- Node colour indicates health: green (up), yellow (degraded), red (down), grey (unknown).

Click any node to open its detail panel.

## Configuration Drift

Navigate to **Infrastructure → Drift** to detect configuration changes across agents.

NOBA takes periodic snapshots of:
- Installed packages (`dpkg`, `rpm`, `apk`)
- Active systemd units
- Network interface configuration
- `/etc` file hashes (configurable list)

When a snapshot differs from the previous baseline, a drift alert is raised. Click **View Diff** to see exactly what changed.

## Topology Export

Click **Export → IaC** in the Infrastructure view to download a YAML representation of your infrastructure suitable for use with Ansible inventories or Terraform locals.

## IaC Export Format

```yaml
hosts:
  - name: web-01
    ip: 192.168.1.10
    os: Ubuntu 24.04
    tags: [web, production]
  - name: nas-01
    ip: 192.168.1.20
    os: TrueNAS SCALE 24.10
    tags: [storage]
```
